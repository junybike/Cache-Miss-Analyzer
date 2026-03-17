#include <iostream>
#include <string>
#include <set>

#include "clang/AST/ASTConsumer.h"
#include "clang/AST/RecursiveASTVisitor.h"
#include "clang/Frontend/FrontendAction.h"
#include "clang/Tooling/Tooling.h"

using namespace clang;

class AccessVisitor : public RecursiveASTVisitor<AccessVisitor> 
{
public:

    bool VisitArraySubscriptExpr(ArraySubscriptExpr *expr) 
    {
        Expr *base = expr->getBase();
        if (DeclRefExpr *DRE = dyn_cast<DeclRefExpr>(base)) 
        {
            std::string var = DRE->getNameInfo().getAsString();
            std::cout << "Array access at " << var << std::endl;
        } 

        return true;
    }

    bool VisitMemberExpr(MemberExpr *expr) 
    {
        if (DeclRefExpr *DRE = dyn_cast<DeclRefExpr>(expr->getBase())) 
        {
            std::string var = DRE->getNameInfo().getAsString();
            std::string field = expr->getMemberNameInfo().getAsString();
            std::cout << "Struct field access: " << var << "->" << field << std::endl;
        }
        return true;
    }
};

class AccessConsumer : public ASTConsumer 
{
public:

    void HandleTranslationUnit(ASTContext &context) override 
    {
        AccessVisitor visitor;
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

int main(int argc, const char **argv)
{
    if (argc < 2)
    {
        std::cerr << "Usage: ast_analyzer <source_file>" << std::endl;
        return 1;
    }

    clang::tooling::runToolOnCodeWithArgs(std::make_unique<AccessAction>(), argv[1], {"-std=c++11"});

    return 0;
}