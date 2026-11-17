# Biblioteca nativa da IA local da Eva (orbita_llama.cpp + llama.cpp num .so só, sem libc++ nem OpenMP à parte), no
# mesmo esquema da transcrição das aulas (tools/aulas/whisper-jni/). Uso (o workflow .github/workflows/llama.yml faz
# isto com o NDK, uma vez por variante):
#   cmake -S tools/eva-local/llama-jni -B build -DLLAMA_DIR=<clone do llama.cpp> -DORBITA_NOME=orbita_llama \
#         [-DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26]
#         [-DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16]
cmake_minimum_required(VERSION 3.14)
project(orbita_llama C CXX)

set(CMAKE_CXX_STANDARD 17)
set(LLAMA_DIR "" CACHE PATH "Clone do llama.cpp")
set(ORBITA_NOME "orbita_llama" CACHE STRING "Nome da biblioteca (lib<nome>.so)")
if (NOT LLAMA_DIR)
  message(FATAL_ERROR "Falta -DLLAMA_DIR=<clone do llama.cpp>")
endif()

# llama.cpp e ggml estáticos, dentro do nosso .so; só a biblioteca (sem common, ferramentas, servidor, testes, HTTPS)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_COMMON OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_APP OFF CACHE BOOL "" FORCE)
set(LLAMA_BUILD_MTMD OFF CACHE BOOL "" FORCE)
set(LLAMA_OPENSSL OFF CACHE BOOL "" FORCE)
set(LLAMA_CURL OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)   # o ggml usa o próprio grupo de threads (sem libomp.so no APK)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)   # compila para o alvo pedido, não para a máquina que compila
set(GGML_LLAMAFILE ON CACHE BOOL "" FORCE) # os kernels sgemm do llamafile: prompt mais rápido na CPU
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_subdirectory(${LLAMA_DIR} llama EXCLUDE_FROM_ALL)

add_library(${ORBITA_NOME} SHARED orbita_llama.cpp)
target_link_libraries(${ORBITA_NOME} PRIVATE llama)
option(ORBITA_TESTE_RECORRENTE "Só no teste do x86: não apaga o fim da memória (usa a cópia da parte fixa)" OFF)
if (ORBITA_TESTE_RECORRENTE)
  target_compile_definitions(${ORBITA_NOME} PRIVATE ORBITA_TESTE_RECORRENTE)
endif()
if (ANDROID)
  target_link_libraries(${ORBITA_NOME} PRIVATE log)
  target_compile_options(${ORBITA_NOME} PRIVATE -O3 -ffunction-sections -fdata-sections)
  # só os símbolos Java_… ficam visíveis (o ggml do whisper e o daqui não se misturam); páginas de 16 KB (Android 15+)
  target_link_options(${ORBITA_NOME} PRIVATE -Wl,--gc-sections -Wl,--exclude-libs,ALL -Wl,-z,max-page-size=16384)
endif()
