cmake_minimum_required(VERSION 3.16)
project(ast_analyzer CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(LLVM REQUIRED CONFIG)
find_package(Clang REQUIRED CONFIG)

add_executable(ast_analyzer ast_analyzer.cpp)
target_include_directories(ast_analyzer PRIVATE
    ${LLVM_INCLUDE_DIRS}
    ${CLANG_INCLUDE_DIRS}
)
target_compile_definitions(ast_analyzer PRIVATE ${LLVM_DEFINITIONS})
target_link_libraries(ast_analyzer PRIVATE clang-cpp LLVM)
