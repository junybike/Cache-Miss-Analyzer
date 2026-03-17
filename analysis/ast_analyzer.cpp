#include <iostream>
#include <string>
#include <set>

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/FrontendAction.h"
#include "clang/Tooling/Tooling.h"
#include "clang/Tooling/CommonOptionsParser.h"

#include "llvm/Support/CommandLine.h"

using namespace clang;

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

class AccessVisitor : public RecursiveASTVisitor<AccessVisitor> 
{
public:

    ASTContext *Context;

    AccessVisitor(ASTContext *context) : Context(context) {}

    bool VisitArraySubscriptExpr(ArraySubscriptExpr *expr) 
    {
        SourceManager &SM = Context->getSourceManager();
        SourceLocation SL = SM.getExpansionLoc(expr->getExprLoc());

        if (SL.isInvalid()) return true;
        if (!SM.isWrittenInMainFile(SL)) return true;

        unsigned line = SM.getSpellingLineNumber(SL);

        Expr *base = unwrapExpr(expr->getBase());
        if (DeclRefExpr *DRE = dyn_cast<DeclRefExpr>(base)) 
        {
            std::string var = DRE->getNameInfo().getAsString();
            std::cout << "Line " << line << ": array access " << var << std::endl;
        } 

        return true;
    }

    bool VisitMemberExpr(MemberExpr *expr) 
    {
        SourceManager &SM = Context->getSourceManager();
        SourceLocation SL = SM.getExpansionLoc(expr->getExprLoc());

        if (SL.isInvalid()) return true;
        if (!SM.isWrittenInMainFile(SL)) return true;

        unsigned line = SM.getSpellingLineNumber(SL);
        
        Expr *base = unwrapExpr(expr->getBase());
        if (DeclRefExpr *DRE = dyn_cast<DeclRefExpr>(base)) 
        {
            std::string var = DRE->getNameInfo().getAsString();
            std::string field = expr->getMemberNameInfo().getAsString();
            std::cout << "Line " << line 
                  << ": struct access " << var << "->" << field 
                  << std::endl;
        }
        return true;
    }

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
            std::string var = DRE->getNameInfo().getAsString();
            std::cout << "Line " << line << ": vector access " << var << std::endl;
        }

        return true;
    }
};

class AccessConsumer : public ASTConsumer 
{
public:

    void HandleTranslationUnit(ASTContext &context) override 
    {
        AccessVisitor visitor(&context);
        visitor.TraverseDecl(context.getTranslationUnitDecl());
    }
};

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