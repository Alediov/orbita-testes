# Ramo `dados`

Saídas dos workflows do espelho do repositório `orbita-testes` (`dados.yml`, `whisper.yml`, `llama.yml`), nos mesmos
caminhos do repositório do app. Commit único, refeito a cada rodada. Só dados públicos e código aberto:

- `app/dados/sia/`, `tools/odontoscan/dados/sia-*`: produção ambulatorial oficial (SIA/SUS, DATASUS), agregada.
- `app/dados/xadrez/problemas.json`: problemas do banco do Lichess (CC0).
- `android-extra/jniLibs/`: whisper.cpp e llama.cpp (MIT) compilados para arm64 com as pontes JNI do espelho.
