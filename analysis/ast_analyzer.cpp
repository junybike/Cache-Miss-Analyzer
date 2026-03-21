#include <iostream>
#include <string>
#include <set>
#include <vector>
#include <map>

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/AST/RecordLayout.h"
#include "clang/Frontend/FrontendAction.h"
#include "clang/Tooling/Tooling.h"
#include "clang/Tooling/CommonOptionsParser.h"

#include "llvm/Support/CommandLine.h"
#include "llvm/Support/JSON.h"
#include "llvm/Support/raw_ostream.h"

using namespace clang;

// Unwrap expressions. Filter out implicit casts to see actual variables in the code.
Expr* unwrapExpr(Expr* expr)
{
    while (true)
    {
        if (auto *ICE = dyn_cast<ImplicitCastExpr>(expr)) expr = ICE->getSubExpr();
        else if (auto *MTE = dyn_cast<MaterializeTemporaryExpr>(expr)) expr = MTE->getSubExpr();
        else break;
    }
    return expr;
}

struct AccessRecord
{
    unsigned line;
    std::string kind;         // "array", "vector", "indirect_array", "indirect_vector",
                              // "strided", "struct_member", "aos_member"
    std::string var;
    std::string element_type;
    std::string struct_type;
    std::string field;
    bool in_loop;
    bool is_ptr_advance;
};

struct FieldRecord
{
    std::string name;
    std::string type;
    uint64_t size;
    uint64_t offset;
};

struct StructRecord
{
    uint64_t size;
    std::vector<FieldRecord> fields;
};

// Traverses the AST to extract struct layouts, variable access patterns,
// loop context, and pointer-advance chains for cache-miss analysis.
class AccessVisitor : public RecursiveASTVisitor<AccessVisitor>
{
public:

    ASTContext *Context;
    int LoopDepth = 0;
    std::vector<AccessRecord> Accesses;
    std::map<std::string, StructRecord> Structs;
    std::set<std::pair<unsigned, std::string>> PtrAdvances;
    std::map<std::string, int> LoopVarDepth;
    std::set<unsigned> Visited2DLines;

    AccessVisitor(ASTContext *context) : Context(context) {}

    // Extracts struct/class layout: field names, types, sizes, byte offsets
    bool VisitRecordDecl(RecordDecl *RD)
    {
        if (!RD->isCompleteDefinition()) return true;

        SourceManager &SM = Context->getSourceManager();
        if (!SM.isWrittenInMainFile(RD->getLocation())) return true;

        std::string name = RD->getNameAsString();
        if (name.empty()) return true;

        const ASTRecordLayout &Layout = Context->getASTRecordLayout(RD);
        StructRecord sr;
        sr.size = Layout.getSize().getQuantity();

        for (auto *field : RD->fields())
        {
            FieldRecord fr;
            fr.name = field->getNameAsString();
            fr.type = field->getType().getAsString();
            fr.size = Context->getTypeSizeInChars(field->getType()).getQuantity();
            fr.offset = Layout.getFieldOffset(field->getFieldIndex()) / 8;
            sr.fields.push_back(fr);
        }

        Structs[name] = sr;
        return true;
    }

    // Extract the induction variable from a for-loop's init statement
    std::string extractLoopVar(ForStmt *S)
    {
        Stmt *init = S->getInit();
        if (!init) return "";

        // for (int i = 0; ...)
        if (auto *DS = dyn_cast<DeclStmt>(init))
        {
            if (DS->isSingleDecl())
                if (auto *VD = dyn_cast<VarDecl>(DS->getSingleDecl()))
                    return VD->getNameAsString();
        }
        // for (i = 0; ...)
        else if (auto *BO = dyn_cast<BinaryOperator>(init))
        {
            if (BO->isAssignmentOp())
            {
                Expr *lhs = unwrapExpr(BO->getLHS());
                if (auto *DRE = dyn_cast<DeclRefExpr>(lhs))
                    return DRE->getNameInfo().getAsString();
            }
        }

        return "";
    }

    // Loop context tracking — increment depth on entry, decrement on exit
    bool TraverseForStmt(ForStmt *S)
    {
        std::string loopVar = extractLoopVar(S);

        LoopDepth++;
        if (!loopVar.empty()) LoopVarDepth[loopVar] = LoopDepth;

        bool result = RecursiveASTVisitor::TraverseForStmt(S);

        if (!loopVar.empty()) LoopVarDepth.erase(loopVar);
        LoopDepth--;
        return result;
    }

    bool TraverseWhileStmt(WhileStmt *S)
    {
        LoopDepth++;
        bool result = RecursiveASTVisitor::TraverseWhileStmt(S);
        LoopDepth--;
        return result;
    }

    bool TraverseDoStmt(DoStmt *S)
    {
        LoopDepth++;
        bool result = RecursiveASTVisitor::TraverseDoStmt(S);
        LoopDepth--;
        return result;
    }

    bool TraverseCXXForRangeStmt(CXXForRangeStmt *S)
    {
        LoopDepth++;
        bool result = RecursiveASTVisitor::TraverseCXXForRangeStmt(S);
        LoopDepth--;
        return result;
    }

    // Pointer-advance detection: tmp = tmp->next
    bool VisitBinaryOperator(BinaryOperator *BO)
    {
        if (!BO->isAssignmentOp()) return true;

        SourceManager &SM = Context->getSourceManager();
        SourceLocation SL = SM.getExpansionLoc(BO->getExprLoc());
        if (SL.isInvalid() || !SM.isWrittenInMainFile(SL)) return true;

        unsigned line = SM.getSpellingLineNumber(SL);

        Expr *lhs = unwrapExpr(BO->getLHS());
        auto *lhsDRE = dyn_cast<DeclRefExpr>(lhs);
        if (!lhsDRE) return true;

        Expr *rhs = unwrapExpr(BO->getRHS());
        auto *rhsME = dyn_cast<MemberExpr>(rhs);
        if (!rhsME) return true;

        Expr *rhsBase = unwrapExpr(rhsME->getBase());
        auto *rhsDRE = dyn_cast<DeclRefExpr>(rhsBase);
        if (!rhsDRE) return true;

        // Compare by name — could false-positive on same-named variables in
        // different scopes on the same line, but this is unlikely in practice.
        if (lhsDRE->getNameInfo().getAsString() == rhsDRE->getNameInfo().getAsString())
        {
            PtrAdvances.insert({line, lhsDRE->getNameInfo().getAsString()});
        }

        return true;
    }

    // Detects array accesses and strided 2D access patterns
    bool VisitArraySubscriptExpr(ArraySubscriptExpr *expr)
    {
        SourceManager &SM = Context->getSourceManager();
        SourceLocation SL = SM.getExpansionLoc(expr->getExprLoc());

        if (SL.isInvalid()) return true;
        if (!SM.isWrittenInMainFile(SL)) return true;

        unsigned line = SM.getSpellingLineNumber(SL);

        // Skip if this line was already recorded by an outer 2D subscript,
        // preventing double-counting of nested array accesses (e.g. arr[r][c])
        if (Visited2DLines.count(line)) return true;

        Expr *base = unwrapExpr(expr->getBase());

        // 2D array: arr[row][col] — check if row index varies faster than col
        if (auto *innerASE = dyn_cast<ArraySubscriptExpr>(base))
        {
            Expr *arrBase = unwrapExpr(innerASE->getBase());
            if (auto *DRE = dyn_cast<DeclRefExpr>(arrBase))
            {
                auto *rowDRE = dyn_cast<DeclRefExpr>(unwrapExpr(innerASE->getIdx()));
                auto *colDRE = dyn_cast<DeclRefExpr>(unwrapExpr(expr->getIdx()));

                if (rowDRE && colDRE)
                {
                    std::string rowVar = rowDRE->getNameInfo().getAsString();
                    std::string colVar = colDRE->getNameInfo().getAsString();
                    auto rowIt = LoopVarDepth.find(rowVar);
                    auto colIt = LoopVarDepth.find(colVar);

                    if (rowIt != LoopVarDepth.end() && colIt != LoopVarDepth.end()
                        && rowIt->second > colIt->second)
                    {
                        Visited2DLines.insert(line);
                        AccessRecord rec;
                        rec.line = line;
                        rec.kind = "strided";
                        rec.var = DRE->getNameInfo().getAsString();
                        rec.element_type = expr->getType().getAsString();
                        rec.in_loop = true;
                        rec.is_ptr_advance = false;
                        Accesses.push_back(rec);
                        return true;
                    }
                }

                // Non-strided 2D access — record as regular array
                AccessRecord rec;
                rec.line = line;
                rec.kind = "array";
                rec.var = DRE->getNameInfo().getAsString();
                rec.element_type = expr->getType().getAsString();
                rec.in_loop = (LoopDepth > 0);
                rec.is_ptr_advance = false;
                Visited2DLines.insert(line);
                Accesses.push_back(rec);
                return true;
            }
        }

        // Regular or indirect 1D array access
        if (DeclRefExpr *DRE = dyn_cast<DeclRefExpr>(base))
        {
            // Indirect access: arr[indices[i]] — index is itself a subscript
            Expr *idx = unwrapExpr(expr->getIdx());
            bool indirect = isa<ArraySubscriptExpr>(idx) ||
                (isa<CXXOperatorCallExpr>(idx) &&
                 cast<CXXOperatorCallExpr>(idx)->getOperator() == OO_Subscript);

            AccessRecord rec;
            rec.line = line;
            rec.kind = indirect ? "indirect_array" : "array";
            rec.var = DRE->getNameInfo().getAsString();
            rec.element_type = expr->getType().getAsString();
            rec.in_loop = (LoopDepth > 0);
            rec.is_ptr_advance = false;
            Accesses.push_back(rec);
        }

        return true;
    }

    // Gets the struct type name from a MemberExpr
    std::string getStructTypeName(MemberExpr *expr)
    {
        auto *RD = dyn_cast<RecordDecl>(expr->getMemberDecl()->getDeclContext());
        if (RD) return RD->getNameAsString();
        return "";
    }

    // Detects struct/member accesses and AoS patterns
    bool VisitMemberExpr(MemberExpr *expr)
    {
        SourceManager &SM = Context->getSourceManager();
        SourceLocation SL = SM.getExpansionLoc(expr->getExprLoc());

        if (SL.isInvalid()) return true;
        if (!SM.isWrittenInMainFile(SL)) return true;

        unsigned line = SM.getSpellingLineNumber(SL);

        Expr *base = unwrapExpr(expr->getBase());

        // AoS pattern: items[i].field — MemberExpr base is ArraySubscriptExpr
        if (auto *ASE = dyn_cast<ArraySubscriptExpr>(base))
        {
            Expr *arrBase = unwrapExpr(ASE->getBase());
            if (auto *DRE = dyn_cast<DeclRefExpr>(arrBase))
            {
                AccessRecord rec;
                rec.line = line;
                rec.kind = "aos_member";
                rec.var = DRE->getNameInfo().getAsString();
                rec.field = expr->getMemberNameInfo().getAsString();
                rec.struct_type = getStructTypeName(expr);
                rec.in_loop = (LoopDepth > 0);
                rec.is_ptr_advance = false;
                Accesses.push_back(rec);
                return true;
            }
        }

        // Vector AoS pattern: vec[i].field — base is CXXOperatorCallExpr (operator[])
        if (auto *OCE = dyn_cast<CXXOperatorCallExpr>(base))
        {
            if (OCE->getOperator() == OO_Subscript)
            {
                Expr *vecObj = unwrapExpr(OCE->getArg(0));
                if (auto *DRE = dyn_cast<DeclRefExpr>(vecObj))
                {
                    AccessRecord rec;
                    rec.line = line;
                    rec.kind = "aos_member";
                    rec.var = DRE->getNameInfo().getAsString();
                    rec.field = expr->getMemberNameInfo().getAsString();
                    rec.struct_type = getStructTypeName(expr);
                    rec.in_loop = (LoopDepth > 0);
                    rec.is_ptr_advance = false;
                    Accesses.push_back(rec);
                    return true;
                }
            }
        }

        // Regular pointer/direct member access: tmp->field or obj.field
        if (DeclRefExpr *DRE = dyn_cast<DeclRefExpr>(base))
        {
            AccessRecord rec;
            rec.line = line;
            rec.kind = "struct_member";
            rec.var = DRE->getNameInfo().getAsString();
            rec.field = expr->getMemberNameInfo().getAsString();
            rec.struct_type = getStructTypeName(expr);
            rec.in_loop = (LoopDepth > 0);
            rec.is_ptr_advance = PtrAdvances.count({line, rec.var}) > 0;
            Accesses.push_back(rec);
        }
        return true;
    }

    // Detects vector accesses (operator[])
    bool VisitCXXOperatorCallExpr(CXXOperatorCallExpr *expr)
    {
        if (expr->getOperator() != OO_Subscript) return true;

        SourceManager &SM = Context->getSourceManager();
        SourceLocation SL = SM.getExpansionLoc(expr->getExprLoc());

        if (SL.isInvalid()) return true;
        if (!SM.isWrittenInMainFile(SL)) return true;

        unsigned line = SM.getSpellingLineNumber(SL);

        Expr *arg = unwrapExpr(expr->getArg(0));
        if (auto *DRE = dyn_cast<DeclRefExpr>(arg))
        {
            // Indirect access: vec[indices[i]] — index is itself a subscript
            Expr *idx = unwrapExpr(expr->getArg(1));
            bool indirect = isa<ArraySubscriptExpr>(idx) ||
                (isa<CXXOperatorCallExpr>(idx) &&
                 cast<CXXOperatorCallExpr>(idx)->getOperator() == OO_Subscript);

            AccessRecord rec;
            rec.line = line;
            rec.kind = indirect ? "indirect_vector" : "vector";
            rec.var = DRE->getNameInfo().getAsString();
            rec.element_type = expr->getType().getAsString();
            rec.in_loop = (LoopDepth > 0);
            rec.is_ptr_advance = false;
            Accesses.push_back(rec);
        }

        return true;
    }

    // Emit all collected data as JSON
    void emitJSON()
    {
        llvm::json::Object root;

        // Structs
        llvm::json::Object structs;
        for (const auto &pair : Structs)
        {
            llvm::json::Object structObj;
            structObj["size"] = static_cast<int64_t>(pair.second.size);

            llvm::json::Array fields;
            for (const auto &fr : pair.second.fields)
            {
                llvm::json::Object fieldObj;
                fieldObj["name"] = fr.name;
                fieldObj["type"] = fr.type;
                fieldObj["size"] = static_cast<int64_t>(fr.size);
                fieldObj["offset"] = static_cast<int64_t>(fr.offset);
                fields.push_back(std::move(fieldObj));
            }
            structObj["fields"] = std::move(fields);
            structs[pair.first] = std::move(structObj);
        }
        root["structs"] = std::move(structs);

        // Accesses
        llvm::json::Array accesses;
        for (const auto &acc : Accesses)
        {
            llvm::json::Object obj;
            obj["line"] = static_cast<int64_t>(acc.line);
            obj["kind"] = acc.kind;
            obj["var"] = acc.var;
            if (!acc.element_type.empty()) obj["element_type"] = acc.element_type;
            if (!acc.struct_type.empty()) obj["struct_type"] = acc.struct_type;
            if (!acc.field.empty()) obj["field"] = acc.field;
            obj["in_loop"] = acc.in_loop;
            if (acc.is_ptr_advance) obj["is_ptr_advance"] = true;
            accesses.push_back(std::move(obj));
        }
        root["accesses"] = std::move(accesses);

        llvm::outs() << llvm::json::Value(std::move(root)) << "\n";
    }
};

// Runs the visitor once the translation unit is fully parsed
class AccessConsumer : public ASTConsumer
{
public:

    void HandleTranslationUnit(ASTContext &context) override
    {
        AccessVisitor visitor(&context);
        visitor.TraverseDecl(context.getTranslationUnitDecl());
        visitor.emitJSON();
    }
};

// Frontend action factory that creates the AccessConsumer for each source file
class AccessAction : public ASTFrontendAction
{
public:

    std::unique_ptr<ASTConsumer> CreateASTConsumer(CompilerInstance &CI, StringRef file) override
    {
        return std::make_unique<AccessConsumer>();
    }
};

static llvm::cl::OptionCategory MyToolCategory("ast-analyzer options");

int main(int argc, const char **argv)
{
    if (argc < 2)
    {
        std::cerr << "Usage: ast_analyzer <source_file>" << std::endl;
        return 1;
    }

    auto parser = tooling::CommonOptionsParser::create(argc, argv, MyToolCategory);

    if (!parser)
    {
        llvm::errs() << "Error creating parser\n";
        return 1;
    }

    tooling::CommonOptionsParser& OptionsParser = parser.get();
    tooling::ClangTool tool(OptionsParser.getCompilations(), OptionsParser.getSourcePathList());

    return tool.run(tooling::newFrontendActionFactory<AccessAction>().get());
}
