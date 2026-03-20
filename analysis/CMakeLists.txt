cmake_minimum_required(VERSION 3.16)
project(ast_analyzer)

find_package(LLVM REQUIRED CONFIG)
find_package(Clang REQUIRED CONFIG)

message(STATUS "LLVM include dirs: ${LLVM_INCLUDE_DIRS}")
message(STATUS "Clang include dirs: ${CLANG_INCLUDE_DIRS}")

add_executable(ast_analyzer ast_analyzer.cpp)

target_include_directories(ast_analyzer PRIVATE
    ${LLVM_INCLUDE_DIRS}
    ${CLANG_INCLUDE_DIRS}
)

add_definitions(${LLVM_DEFINITIONS})

target_link_libraries(ast_analyzer
    clang-cpp
    LLVMSupport
)