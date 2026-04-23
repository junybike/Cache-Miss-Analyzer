// Clang tool: scan a C++ translation unit and emit, as JSON:
//   - struct/class field layouts
//   - each variable access (arrays, vectors, struct members, AoS members,
//     pointer advances, strided 2D accesses, indirect/random accesses)
// The output is consumed downstream to correlate with perf cache-miss data.

#include <map>
#include <set>
#include <string>
#include <unordered_set>
#include <vector>

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/RecordLayout.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/FrontendAction.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Tooling.h"

#include "llvm/Support/CommandLine.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

namespace {

struct Access {
        unsigned line;
        std::string kind;
        std::string var;
        std::string function;
        std::string element_type;
        std::string struct_type;
        std::string field;
        std::string index_var;
        bool in_loop = false;
        bool is_ptr_advance = false;
};

struct Field {
        std::string name, type;
        uint64_t size, offset;
};

struct Struct {
        uint64_t size;
        std::vector<Field> fields;
};

enum class ShareKind {
        CapturedByRef,
        PassedByPtr,
        PassedByRef,
        GlobalOrStatic,
};

static std::string shareKindStr(ShareKind sk) {
        switch (sk) {
        case ShareKind::CapturedByRef:  return "captured_by_ref";
        case ShareKind::PassedByPtr:    return "passed_by_ptr";
        case ShareKind::PassedByRef:    return "passed_by_ref";
        case ShareKind::GlobalOrStatic: return "global_or_static";
        }
        return "unknown";
}

struct SharedVar {
        std::string name, type, thread_api;
        ShareKind kind;
        unsigned line;
};

class Visitor : public clang::RecursiveASTVisitor<Visitor> {
        clang::ASTContext &Ctx;

        std::string CurrentFunction;
        int LoopDepth = 0;
        std::map<std::string, std::vector<int>> LoopVarDepth;

        std::unordered_set<const clang::Expr *> Consumed;

        std::set<std::pair<unsigned, std::string>> PtrAdvances;

        std::vector<Access> Accesses;
        std::map<std::string, Struct> Structs;

        bool IsMultithreaded = false;
        std::vector<SharedVar> SharedCandidates;
        std::set<std::string> ThreadFnNames;
        std::set<std::string> GlobalVarNames;

public:
        explicit Visitor(clang::ASTContext &c) : Ctx(c) {}

        // ---- source-location helpers

        bool inMainFile(clang::SourceLocation loc) const {
                auto &SM = Ctx.getSourceManager();
                loc = SM.getExpansionLoc(loc);
                return loc.isValid() && SM.isWrittenInMainFile(loc);
        }

        unsigned lineOf(const clang::Expr *e) const {
                auto &SM = Ctx.getSourceManager();
                return SM.getExpansionLineNumber(SM.getExpansionLoc(e->getExprLoc()));
        }

        // ---- expression resolution

        std::string resolveVar(const clang::Expr *e) const {
                e = e->IgnoreParenImpCasts();
                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(e))
                        return DRE->getNameInfo().getAsString();
                if (llvm::isa<clang::CXXThisExpr>(e))
                        return "this";
                if (auto *ME = llvm::dyn_cast<clang::MemberExpr>(e)) {
                        std::string base = resolveVar(ME->getBase());
                        if (base.empty()) return "";
                        return base + "." + ME->getMemberNameInfo().getAsString();
                }
                if (auto *UO = llvm::dyn_cast<clang::UnaryOperator>(e))
                        if (UO->getOpcode() == clang::UO_Deref)
                                return resolveVar(UO->getSubExpr());
                return "";
        }

        const clang::ValueDecl *resolveDecl(const clang::Expr *e) const {
                e = e->IgnoreParenImpCasts();
                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(e)) return DRE->getDecl();
                if (auto *ME = llvm::dyn_cast<clang::MemberExpr>(e))   return ME->getMemberDecl();
                if (auto *UO = llvm::dyn_cast<clang::UnaryOperator>(e))
                        if (UO->getOpcode() == clang::UO_Deref)
                                return resolveDecl(UO->getSubExpr());
                return nullptr;
        }

        std::string qualifiedRecord(const clang::RecordDecl *RD) const {
                if (!RD) return "";
                if (!RD->getName().empty())
                        return RD->getQualifiedNameAsString();
                // Anonymous struct — look for a typedef alias (e.g. typedef struct { ... } t_speed;)
                if (auto *TD = RD->getTypedefNameForAnonDecl())
                        return TD->getNameAsString();
                return "";
        }

        std::string structTypeOf(const clang::MemberExpr *ME) const {
                clang::QualType t = ME->getBase()->IgnoreParenImpCasts()->getType();
                if (t->isPointerType()) t = t->getPointeeType();
                if (const auto *rt = t->getAs<clang::RecordType>())
                        return qualifiedRecord(rt->getDecl());
                if (auto *parent = llvm::dyn_cast<clang::RecordDecl>(ME->getMemberDecl()->getDeclContext()))
                        return qualifiedRecord(parent);
                return "";
        }

        // ---- function tracking

        bool TraverseFunctionDecl(clang::FunctionDecl *FD) {
                std::string prev = CurrentFunction;
                CurrentFunction = FD->getQualifiedNameAsString();
                bool r = clang::RecursiveASTVisitor<Visitor>::TraverseFunctionDecl(FD);
                CurrentFunction = prev;
                return r;
        }

        bool TraverseCXXMethodDecl(clang::CXXMethodDecl *MD) {
                std::string prev = CurrentFunction;
                CurrentFunction = MD->getQualifiedNameAsString();
                bool r = clang::RecursiveASTVisitor<Visitor>::TraverseCXXMethodDecl(MD);
                CurrentFunction = prev;
                return r;
        }

        // ---- loop tracking

        std::vector<std::string> initVars(const clang::Stmt *init) const {
                std::vector<std::string> v;
                if (auto *DS = llvm::dyn_cast_or_null<clang::DeclStmt>(init)) {
                        for (const clang::Decl *d : DS->decls())
                                if (auto *VD = llvm::dyn_cast<clang::VarDecl>(d))
                                        v.push_back(VD->getNameAsString());
                } else if (auto *BO = llvm::dyn_cast_or_null<clang::BinaryOperator>(init)) {
                        if (BO->isAssignmentOp())
                                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(BO->getLHS()->IgnoreParenImpCasts()))
                                        v.push_back(DRE->getNameInfo().getAsString());
                }
                return v;
        }

        bool TraverseForStmt(clang::ForStmt *S) {
                auto vars = initVars(S->getInit());
                LoopDepth++;
                for (auto &v : vars) LoopVarDepth[v].push_back(LoopDepth);
                bool r = clang::RecursiveASTVisitor<Visitor>::TraverseForStmt(S);
                for (auto &v : vars) {
                        auto &stk = LoopVarDepth[v];
                        stk.pop_back();
                        if (stk.empty()) LoopVarDepth.erase(v);
                }
                LoopDepth--;
                return r;
        }
        bool TraverseWhileStmt(clang::WhileStmt *S) {
                LoopDepth++;
                bool r = clang::RecursiveASTVisitor<Visitor>::TraverseWhileStmt(S);
                LoopDepth--;
                return r;
        }
        bool TraverseDoStmt(clang::DoStmt *S) {
                LoopDepth++;
                bool r = clang::RecursiveASTVisitor<Visitor>::TraverseDoStmt(S);
                LoopDepth--;
                return r;
        }
        bool TraverseCXXForRangeStmt(clang::CXXForRangeStmt *S) {
                LoopDepth++;
                bool r = clang::RecursiveASTVisitor<Visitor>::TraverseCXXForRangeStmt(S);
                LoopDepth--;
                return r;
        }

        int depthOf(const std::string &var) const {
                auto it = LoopVarDepth.find(var);
                return (it == LoopVarDepth.end() || it->second.empty())
                           ? -1 : it->second.back();
        }

        // ---- record layouts

        void collectFields(const clang::RecordDecl *RD, const clang::ASTRecordLayout &layout,
                           std::vector<Field> &out) {
                for (auto *f : RD->fields()) {
                        if (f->isAnonymousStructOrUnion()) {
                                if (auto *inner = f->getType()->getAsRecordDecl())
                                        if (inner->isCompleteDefinition())
                                                collectFields(inner, Ctx.getASTRecordLayout(inner), out);
                                continue;
                        }
                        out.push_back({
                                f->getNameAsString(),
                                f->getType().getAsString(),
                                static_cast<uint64_t>(Ctx.getTypeSizeInChars(f->getType()).getQuantity()),
                                layout.getFieldOffset(f->getFieldIndex()) / 8,
                        });
                }
        }

        bool VisitRecordDecl(clang::RecordDecl *RD) {
                if (!RD->isCompleteDefinition()) return true;
                if (!inMainFile(RD->getLocation())) return true;

                std::string name = qualifiedRecord(RD);
                if (name.empty()) return true;

                const clang::ASTRecordLayout &layout = Ctx.getASTRecordLayout(RD);
                Struct sr;
                sr.size = layout.getSize().getQuantity();
                collectFields(RD, layout, sr.fields);
                Structs[name] = std::move(sr);
                return true;
        }

        // ---- global/static variable tracking

        bool VisitVarDecl(clang::VarDecl *VD) {
                if (!VD->hasGlobalStorage()) return true;
                if (!inMainFile(VD->getLocation())) return true;
                GlobalVarNames.insert(VD->getNameAsString());
                return true;
        }

        // ---- pointer advance: `p = p->next`

        bool VisitBinaryOperator(clang::BinaryOperator *BO) {
                if (!BO->isAssignmentOp()) return true;
                if (!inMainFile(BO->getExprLoc())) return true;

                auto *rhsME = llvm::dyn_cast<clang::MemberExpr>(BO->getRHS()->IgnoreParenImpCasts());
                if (!rhsME) return true;

                const clang::ValueDecl *lhs = resolveDecl(BO->getLHS());
                const clang::ValueDecl *rhs = resolveDecl(rhsME->getBase());
                if (!lhs || !rhs || lhs != rhs) return true;

                PtrAdvances.emplace(lineOf(BO), resolveVar(BO->getLHS()));
                return true;
        }

        // ---- access recording

        void emit(const clang::Expr *at, std::string kind, std::string var,
                  std::string elem_type = "", std::string struct_type = "",
                  std::string field = "", std::string index_var = "") {
                Access a;
                a.line = lineOf(at);
                a.kind = std::move(kind);
                a.var = std::move(var);
                a.function = CurrentFunction;
                a.element_type = std::move(elem_type);
                a.struct_type = std::move(struct_type);
                a.field = std::move(field);
                a.index_var = std::move(index_var);
                a.in_loop = LoopDepth > 0;
                a.is_ptr_advance = PtrAdvances.count({a.line, a.var}) > 0;
                Accesses.push_back(std::move(a));
        }

        bool isStrided(const clang::Expr *outerIdx, const clang::Expr *innerIdx) const {
                auto *o = llvm::dyn_cast<clang::DeclRefExpr>(outerIdx->IgnoreParenImpCasts());
                auto *i = llvm::dyn_cast<clang::DeclRefExpr>(innerIdx->IgnoreParenImpCasts());
                if (!o || !i) return false;
                int od = depthOf(o->getNameInfo().getAsString());
                int id = depthOf(i->getNameInfo().getAsString());
                return od > 0 && id > 0 && od > id;
        }

        bool indirectIndex(const clang::Expr *idx) const {
                idx = idx->IgnoreParenImpCasts();
                if (llvm::isa<clang::ArraySubscriptExpr>(idx)) return true;
                if (auto *call = llvm::dyn_cast<clang::CXXOperatorCallExpr>(idx))
                        return call->getOperator() == clang::OO_Subscript;
                return false;
        }

        std::string indexArrayName(const clang::Expr *idx) const {
                idx = idx->IgnoreParenImpCasts();
                if (auto *ase = llvm::dyn_cast<clang::ArraySubscriptExpr>(idx))
                        return resolveVar(ase->getBase());
                if (auto *call = llvm::dyn_cast<clang::CXXOperatorCallExpr>(idx))
                        if (call->getOperator() == clang::OO_Subscript && call->getNumArgs() >= 1)
                                return resolveVar(call->getArg(0));
                return "";
        }

        bool VisitArraySubscriptExpr(clang::ArraySubscriptExpr *expr) {
                if (!inMainFile(expr->getExprLoc()) || Consumed.count(expr)) return true;

                const clang::Expr *base = expr->getBase()->IgnoreParenImpCasts();

                if (auto *inner = llvm::dyn_cast<clang::ArraySubscriptExpr>(base)) {
                        Consumed.insert(inner);
                        std::string var = resolveVar(inner->getBase());
                        if (var.empty()) return true;
                        bool strided = isStrided(inner->getIdx(), expr->getIdx());
                        emit(expr, strided ? "strided" : "array", var,
                             expr->getType().getAsString());
                        return true;
                }

                std::string var = resolveVar(base);
                if (var.empty()) return true;
                bool indirect = indirectIndex(expr->getIdx());
                emit(expr, indirect ? "indirect_array" : "array", var,
                     expr->getType().getAsString(), "", "",
                     indirect ? indexArrayName(expr->getIdx()) : "");
                return true;
        }

        bool VisitMemberExpr(clang::MemberExpr *expr) {
                if (!inMainFile(expr->getExprLoc()) || Consumed.count(expr)) return true;

                const clang::Expr *base = expr->getBase()->IgnoreParenImpCasts();
                std::string field = expr->getMemberNameInfo().getAsString();
                std::string structType = structTypeOf(expr);

                if (auto *ase = llvm::dyn_cast<clang::ArraySubscriptExpr>(base)) {
                        std::string var = resolveVar(ase->getBase());
                        if (var.empty()) return true;
                        Consumed.insert(ase);
                        emit(expr, "aos_member", var, "", structType, field);
                        return true;
                }

                if (auto *call = llvm::dyn_cast<clang::CXXOperatorCallExpr>(base)) {
                        if (call->getOperator() == clang::OO_Subscript && call->getNumArgs() >= 1) {
                                std::string var = resolveVar(call->getArg(0));
                                if (var.empty()) return true;
                                Consumed.insert(call);
                                emit(expr, "aos_member", var, "", structType, field);
                                return true;
                        }
                }

                std::string var = resolveVar(base);
                if (var.empty()) return true;
                emit(expr, "struct_member", var, "", structType, field);
                return true;
        }

        bool VisitCXXOperatorCallExpr(clang::CXXOperatorCallExpr *expr) {
                if (expr->getOperator() != clang::OO_Subscript) return true;
                if (!inMainFile(expr->getExprLoc()) || Consumed.count(expr)) return true;
                if (expr->getNumArgs() < 2) return true;

                const clang::Expr *obj = expr->getArg(0)->IgnoreParenImpCasts();
                const clang::Expr *idx = expr->getArg(1);

                if (auto *inner = llvm::dyn_cast<clang::CXXOperatorCallExpr>(obj)) {
                        if (inner->getOperator() == clang::OO_Subscript && inner->getNumArgs() >= 2) {
                                Consumed.insert(inner);
                                std::string var = resolveVar(inner->getArg(0));
                                if (var.empty()) return true;
                                bool strided = isStrided(inner->getArg(1), idx);
                                emit(expr, strided ? "strided" : "vector", var,
                                     expr->getType().getAsString());
                                return true;
                        }
                }

                std::string var = resolveVar(obj);
                if (var.empty()) return true;
                bool indirect = indirectIndex(idx);
                emit(expr, indirect ? "indirect_vector" : "vector", var,
                     expr->getType().getAsString(), "", "",
                     indirect ? indexArrayName(idx) : "");
                return true;
        }

        // ---- multithreading detection

        bool VisitCXXConstructExpr(clang::CXXConstructExpr *expr) {
                if (!inMainFile(expr->getExprLoc())) return true;
                auto *CD = expr->getConstructor();
                if (!CD) return true;
                std::string name = CD->getParent()->getNameAsString();
                if (name == "thread" || name == "jthread") {
                        IsMultithreaded = true;
                        detectSharedArgs(expr, lineOf(expr), "std::thread");
                }
                return true;
        }

        bool VisitCallExpr(clang::CallExpr *expr) {
                if (!inMainFile(expr->getExprLoc())) return true;
                clang::FunctionDecl *FD = expr->getDirectCallee();
                if (!FD) return true;
                std::string name = FD->getNameAsString();
                if (name == "async") {
                        if (FD->getQualifiedNameAsString().find("std::") != std::string::npos) {
                                IsMultithreaded = true;
                                detectSharedArgs(expr, lineOf(expr), "std::async");
                        }
                } else if (name == "pthread_create") {
                        IsMultithreaded = true;
                        detectPthreadCreate(expr, lineOf(expr));
                }
                return true;
        }

        bool VisitFunctionDecl(clang::FunctionDecl *FD) {
                std::string name = FD->getNameAsString();
                if (name.find("omp_outlined") != std::string::npos ||
                    name.find(".omp.") != std::string::npos)
                        IsMultithreaded = true;
                for (auto *attr : FD->attrs())
                        if (std::string(attr->getSpelling()).find("omp") != std::string::npos)
                                IsMultithreaded = true;
                return true;
        }

        // ---- shared-variable helpers

        template <typename CallLike>
        void detectSharedArgs(CallLike *expr, unsigned line, const std::string &api) {
                if (expr->getNumArgs() == 0) return;
                const clang::Expr *callable = expr->getArg(0)->IgnoreParenImpCasts();

                if (auto *LE = llvm::dyn_cast<clang::LambdaExpr>(callable)) {
                        for (const auto &capture : LE->captures()) {
                                if (capture.getCaptureKind() == clang::LCK_ByRef) {
                                        if (auto *VD = llvm::dyn_cast<clang::VarDecl>(capture.getCapturedVar())) {
                                                SharedCandidates.push_back({
                                                        VD->getNameAsString(),
                                                        VD->getType().getAsString(),
                                                        api, ShareKind::CapturedByRef, line,
                                                });
                                        }
                                }
                        }
                        collectThreadFnName(callable);
                } else if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(callable)) {
                        ThreadFnNames.insert(DRE->getNameInfo().getAsString());
                }

                for (unsigned i = 1; i < expr->getNumArgs(); ++i) {
                        const clang::Expr *arg = expr->getArg(i)->IgnoreParenImpCasts();
                        clang::QualType qt = arg->getType();

                        if (auto *CE = llvm::dyn_cast<clang::CallExpr>(arg)) {
                                if (const clang::FunctionDecl *fd = CE->getDirectCallee()) {
                                        std::string fn = fd->getQualifiedNameAsString();
                                        if ((fn == "std::ref" || fn == "std::cref") && CE->getNumArgs() == 1) {
                                                const clang::Expr *inner = CE->getArg(0)->IgnoreParenImpCasts();
                                                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(inner)) {
                                                        SharedCandidates.push_back({
                                                                DRE->getNameInfo().getAsString(),
                                                                DRE->getDecl()->getType().getAsString(),
                                                                api, ShareKind::PassedByRef, line,
                                                        });
                                                }
                                                continue;
                                        }
                                }
                        }

                        if (qt->isPointerType()) {
                                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(arg)) {
                                        SharedCandidates.push_back({
                                                DRE->getNameInfo().getAsString(),
                                                DRE->getDecl()->getType().getAsString(),
                                                api, ShareKind::PassedByPtr, line,
                                        });
                                } else if (auto *UO = llvm::dyn_cast<clang::UnaryOperator>(arg)) {
                                        if (UO->getOpcode() == clang::UO_AddrOf) {
                                                const clang::Expr *operand = UO->getSubExpr()->IgnoreParenImpCasts();
                                                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(operand)) {
                                                        SharedCandidates.push_back({
                                                                DRE->getNameInfo().getAsString(),
                                                                DRE->getDecl()->getType().getAsString(),
                                                                api, ShareKind::PassedByPtr, line,
                                                        });
                                                }
                                        }
                                }
                        }
                }
        }

        void detectPthreadCreate(clang::CallExpr *expr, unsigned line) {
                if (expr->getNumArgs() < 3) return;
                const clang::Expr *fnArg = expr->getArg(2)->IgnoreParenImpCasts();
                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(fnArg))
                        ThreadFnNames.insert(DRE->getNameInfo().getAsString());

                if (expr->getNumArgs() < 4) return;
                const clang::Expr *dataArg = expr->getArg(3)->IgnoreParenImpCasts();

                const clang::Expr *inner = dataArg;
                if (auto *CCE = llvm::dyn_cast<clang::CStyleCastExpr>(inner))
                        inner = CCE->getSubExpr()->IgnoreParenImpCasts();

                if (auto *UO = llvm::dyn_cast<clang::UnaryOperator>(inner)) {
                        if (UO->getOpcode() == clang::UO_AddrOf) {
                                const clang::Expr *operand = UO->getSubExpr()->IgnoreParenImpCasts();
                                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(operand)) {
                                        SharedCandidates.push_back({
                                                DRE->getNameInfo().getAsString(),
                                                DRE->getDecl()->getType().getAsString(),
                                                "pthread", ShareKind::PassedByPtr, line,
                                        });
                                }
                        }
                }
        }

        void collectThreadFnName(const clang::Expr *expr) {
                if (auto *DRE = llvm::dyn_cast<clang::DeclRefExpr>(expr->IgnoreParenImpCasts()))
                        ThreadFnNames.insert(DRE->getNameInfo().getAsString());
        }

        void collectImplicitRefCaptures(clang::LambdaExpr *Lambda, unsigned line,
                                        const std::string &api) {
                struct RefCollector : public clang::RecursiveASTVisitor<RefCollector> {
                        std::vector<std::pair<std::string, std::string>> vars;
                        bool VisitDeclRefExpr(clang::DeclRefExpr *DRE) {
                                if (auto *VD = llvm::dyn_cast<clang::VarDecl>(DRE->getDecl()))
                                        if (VD->isLocalVarDecl() && !VD->isStaticLocal())
                                                vars.push_back({VD->getNameAsString(),
                                                                VD->getType().getAsString()});
                                return true;
                        }
                };
                RefCollector collector;
                collector.TraverseStmt(Lambda->getBody());

                std::set<std::string> seen;
                for (auto &[name, type] : collector.vars) {
                        if (!seen.insert(name).second) continue;
                        SharedCandidates.push_back({name, type, api,
                                                    ShareKind::CapturedByRef, line});
                }
        }

        void scanThreadFunctionsForGlobals(clang::TranslationUnitDecl *TU) {
                if (ThreadFnNames.empty() || GlobalVarNames.empty()) return;

                struct Scanner : public clang::RecursiveASTVisitor<Scanner> {
                        Visitor *Parent;
                        clang::ASTContext &Ctx;
                        bool InsideThreadFn = false;

                        Scanner(Visitor *p, clang::ASTContext &ctx) : Parent(p), Ctx(ctx) {}

                        bool TraverseFunctionDecl(clang::FunctionDecl *FD) {
                                bool prev = InsideThreadFn;
                                InsideThreadFn = Parent->ThreadFnNames.count(FD->getNameAsString()) > 0;
                                bool r = clang::RecursiveASTVisitor<Scanner>::TraverseFunctionDecl(FD);
                                InsideThreadFn = prev;
                                return r;
                        }

                        bool VisitDeclRefExpr(clang::DeclRefExpr *DRE) {
                                if (!InsideThreadFn) return true;
                                auto *VD = llvm::dyn_cast<clang::VarDecl>(DRE->getDecl());
                                if (!VD || !VD->hasGlobalStorage()) return true;
                                std::string name = VD->getNameAsString();
                                if (!Parent->GlobalVarNames.count(name)) return true;

                                auto &SM = Ctx.getSourceManager();
                                clang::SourceLocation SL = SM.getExpansionLoc(DRE->getLocation());
                                if (SL.isInvalid() || !SM.isWrittenInMainFile(SL)) return true;
                                unsigned line = SM.getSpellingLineNumber(SL);

                                for (auto &existing : Parent->SharedCandidates)
                                        if (existing.name == name &&
                                            existing.kind == ShareKind::GlobalOrStatic)
                                                return true;

                                Parent->SharedCandidates.push_back({
                                        name, VD->getType().getAsString(),
                                        "global", ShareKind::GlobalOrStatic, line,
                                });
                                return true;
                        }
                };

                Scanner scanner(this, Ctx);
                scanner.TraverseDecl(TU);
        }

        void finalize(clang::TranslationUnitDecl *TU) {
                if (IsMultithreaded)
                        scanThreadFunctionsForGlobals(TU);
        }

        // ---- JSON emission

        llvm::json::Value toJSON() const {
                llvm::json::Object structs;
                for (auto &[name, sr] : Structs) {
                        llvm::json::Array fields;
                        for (auto &f : sr.fields) {
                                fields.push_back(llvm::json::Object{
                                        {"name", f.name},
                                        {"type", f.type},
                                        {"size", static_cast<int64_t>(f.size)},
                                        {"offset", static_cast<int64_t>(f.offset)},
                                });
                        }
                        structs[name] = llvm::json::Object{
                                {"size", static_cast<int64_t>(sr.size)},
                                {"fields", std::move(fields)},
                        };
                }

                llvm::json::Array accesses;
                for (auto &a : Accesses) {
                        llvm::json::Object o;
                        o["line"] = static_cast<int64_t>(a.line);
                        o["kind"] = a.kind;
                        o["var"] = a.var;
                        if (!a.function.empty())     o["function"] = a.function;
                        if (!a.element_type.empty()) o["element_type"] = a.element_type;
                        if (!a.struct_type.empty())  o["struct_type"] = a.struct_type;
                        if (!a.field.empty())        o["field"] = a.field;
                        if (!a.index_var.empty())    o["index_var"] = a.index_var;
                        o["in_loop"] = a.in_loop;
                        if (a.is_ptr_advance) o["is_ptr_advance"] = true;
                        accesses.push_back(std::move(o));
                }

                llvm::json::Object root;
                root["multithreaded"] = IsMultithreaded;
                if (IsMultithreaded) {
                        llvm::json::Array candidates;
                        for (const auto &sc : SharedCandidates) {
                                candidates.push_back(llvm::json::Object{
                                        {"var",        sc.name},
                                        {"type",       sc.type},
                                        {"share_kind", shareKindStr(sc.kind)},
                                        {"line",       static_cast<int64_t>(sc.line)},
                                        {"thread_api", sc.thread_api},
                                });
                        }
                        root["shared_candidates"] = std::move(candidates);
                }
                root["structs"] = std::move(structs);
                root["accesses"] = std::move(accesses);
                return llvm::json::Value(std::move(root));
        }
};

class Consumer : public clang::ASTConsumer {
public:
        void HandleTranslationUnit(clang::ASTContext &ctx) override {
                Visitor v(ctx);
                auto *TU = ctx.getTranslationUnitDecl();
                v.TraverseDecl(TU);
                v.finalize(TU);
                llvm::outs() << v.toJSON() << "\n";
        }
};

class Action : public clang::ASTFrontendAction {
public:
        std::unique_ptr<clang::ASTConsumer> CreateASTConsumer(clang::CompilerInstance &,
                                                              llvm::StringRef) override {
                return std::make_unique<Consumer>();
        }
};

llvm::cl::OptionCategory ToolCategory("ast-analyzer options");

} // namespace

int main(int argc, const char **argv) {
        auto parser = clang::tooling::CommonOptionsParser::create(argc, argv, ToolCategory);
        if (!parser) {
                llvm::errs() << parser.takeError();
                return 1;
        }
        clang::tooling::ClangTool tool(parser->getCompilations(), parser->getSourcePathList());
        return tool.run(clang::tooling::newFrontendActionFactory<Action>().get());
}
