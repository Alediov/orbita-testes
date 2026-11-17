#!/bin/sh
# Confere a ponte JNI da transcrição no notebook (x86_64, sem o NDK): compila o whisper.cpp + orbita_whisper.cpp e roda
# o TesteWhisper com um modelo ggml e um WAV de 16 kHz mono. Uso:
#   sh tools/aulas/whisper-jni/teste_x86.sh <clone do whisper.cpp> <pasta de trabalho> [modelo.bin] [audio.wav]
# Sem modelo, usa o de teste do próprio whisper.cpp (só o vocabulário: confere a carga e a assinatura dos métodos).
set -e
W=$(cd "$1" && pwd); T=$2; mkdir -p "$T"; T=$(cd "$T" && pwd)
AQUI=$(cd "$(dirname "$0")" && pwd); RAIZ=$(cd "$AQUI/../../.." && pwd)
JH=$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")
cmake -S "$AQUI" -B "$T/build" -DWHISPER_DIR="$W" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-I$JH/include -I$JH/include/linux" > "$T/cmake.log"
cmake --build "$T/build" -j"$(nproc)" --target orbita_whisper > "$T/build.log"
mkdir -p "$T/classes"
javac -d "$T/classes" "$RAIZ/android-extra/java/br/alediov/odontoquest/Whisper.java" "$AQUI/TesteWhisper.java"
java -Djava.library.path="$T/build" -cp "$T/classes" br.alediov.odontoquest.TesteWhisper "${3:-$W/models/for-tests-ggml-tiny.bin}" "${4:-$W/samples/jfk.wav}"
