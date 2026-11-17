# Biblioteca nativa da transcrição das aulas (orbita_whisper.cpp + whisper.cpp num .so só, sem libc++ nem OpenMP à
# parte). Uso (o workflow .github/workflows/whisper.yml faz isto com o NDK, uma vez por variante):
#   cmake -S tools/aulas/whisper-jni -B build -DWHISPER_DIR=<clone do whisper.cpp> -DORBITA_NOME=orbita_whisper \
#         [-DCMAKE_TOOLCHAIN_FILE=$NDK/build/cmake/android.toolchain.cmake -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-26]
#         [-DGGML_CPU_ARM_ARCH=armv8.2-a+dotprod+fp16]
cmake_minimum_required(VERSION 3.14)
project(orbita_whisper C CXX)

set(CMAKE_CXX_STANDARD 17)
set(WHISPER_DIR "" CACHE PATH "Clone do whisper.cpp")
set(ORBITA_NOME "orbita_whisper" CACHE STRING "Nome da biblioteca (lib<nome>.so)")
if (NOT WHISPER_DIR)
  message(FATAL_ERROR "Falta -DWHISPER_DIR=<clone do whisper.cpp>")
endif()

# whisper.cpp e ggml estáticos, dentro do nosso .so
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
set(WHISPER_CURL OFF CACHE BOOL "" FORCE)
set(WHISPER_SDL2 OFF CACHE BOOL "" FORCE)
set(GGML_OPENMP OFF CACHE BOOL "" FORCE)   # o ggml usa o próprio grupo de threads (sem libomp.so no APK)
set(GGML_NATIVE OFF CACHE BOOL "" FORCE)   # compila para o alvo pedido, não para a máquina que compila
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_subdirectory(${WHISPER_DIR} whisper EXCLUDE_FROM_ALL)

add_library(${ORBITA_NOME} SHARED orbita_whisper.cpp)
target_link_libraries(${ORBITA_NOME} PRIVATE whisper)
if (ANDROID)
  target_link_libraries(${ORBITA_NOME} PRIVATE log)
  target_compile_options(${ORBITA_NOME} PRIVATE -O3 -ffunction-sections -fdata-sections)
  # só os símbolos Java_… ficam visíveis; -z max-page-size=16384: aparelhos com páginas de 16 KB (Android 15+)
  target_link_options(${ORBITA_NOME} PRIVATE -Wl,--gc-sections -Wl,--exclude-libs,ALL -Wl,-z,max-page-size=16384)
endif()
