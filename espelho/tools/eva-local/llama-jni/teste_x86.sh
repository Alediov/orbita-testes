#!/bin/sh
# Confere a ponte JNI da IA local da Eva no notebook (x86_64, sem o NDK): compila o llama.cpp + orbita_llama.cpp e roda
# o TesteLlama com um modelo GGUF. Uso:
#   sh tools/eva-local/llama-jni/teste_x86.sh <clone do llama.cpp> <pasta de trabalho> [modelo.gguf]
# Sem modelo, monta um minúsculo de pesos aleatórios (gerar_modelo_teste.py, com o vocabulário do Qwen 2 que vem no
# próprio llama.cpp): a resposta sai sem sentido, mas confere a carga, o modelo de conversa, o reaproveitamento da
# memória, os pedaços em UTF-8, o parar e a liberação.
set -e
L=$(cd "$1" && pwd); T=$2; mkdir -p "$T"; T=$(cd "$T" && pwd)
AQUI=$(cd "$(dirname "$0")" && pwd); RAIZ=$(cd "$AQUI/../../.." && pwd)
JH=$(dirname "$(dirname "$(readlink -f "$(command -v javac)")")")
cmake -S "$AQUI" -B "$T/build" -DLLAMA_DIR="$L" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-I$JH/include -I$JH/include/linux" > "$T/cmake.log"
cmake --build "$T/build" -j"$(nproc)" --target orbita_llama > "$T/build.log"
M=${3:-}
if [ -z "$M" ]; then
  M="$T/minusculo.gguf"
  [ -f "$M" ] || PYTHONPATH="$L/gguf-py" python3 "$AQUI/gerar_modelo_teste.py" "$L/models/ggml-vocab-qwen2.gguf" "$M"
fi
mkdir -p "$T/classes"
javac -d "$T/classes" "$RAIZ/android-extra/java/br/alediov/odontoquest/Whisper.java" "$RAIZ/android-extra/java/br/alediov/odontoquest/Llama.java" "$AQUI/TesteLlama.java"
java -Djava.library.path="$T/build" -cp "$T/classes" br.alediov.odontoquest.TesteLlama "$M"
# de novo, como num modelo híbrido (o Qwen 3.5 tem camadas recorrentes): o reaproveitamento vem da cópia da parte fixa
cmake -S "$AQUI" -B "$T/build-rec" -DLLAMA_DIR="$L" -DCMAKE_BUILD_TYPE=Release -DORBITA_TESTE_RECORRENTE=ON -DCMAKE_CXX_FLAGS="-I$JH/include -I$JH/include/linux" > "$T/cmake-rec.log"
cmake --build "$T/build-rec" -j"$(nproc)" --target orbita_llama > "$T/build-rec.log"
echo "--- como recorrente (cópia da parte fixa)"
java -Djava.library.path="$T/build-rec" -cp "$T/classes" br.alediov.odontoquest.TesteLlama "$M"
