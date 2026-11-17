// Ponte JNI entre o Órbita (Whisper.java) e o whisper.cpp (MIT), para transcrever as aulas gravadas no próprio
// celular (gravação das aulas, docs/plano-gravacao.md). Compilado para arm64-v8a pelo workflow manual
// .github/workflows/whisper.yml, que guarda as bibliotecas prontas em android-extra/jniLibs/arm64-v8a/; no notebook,
// tools/aulas/whisper-jni/teste_x86.sh compila para x86 só para conferir esta ponte.
//
// Métodos (classe br.alediov.odontoquest.Whisper):
//   long   iniciar(String modelo, int threads)                 contexto (0 se falhou)
//   byte[] transcrever(long ctx, float[] pcm, String lingua, String prompt, int threads, String vad, Progresso p)
//          → JSON em UTF-8: [[ini_ms, fim_ms, "texto", prob_sem_fala], ...] (null se falhou ou foi interrompido)
//   void   abortar(boolean sim)                                 pede para parar a transcrição em andamento
//   void   liberar(long ctx)
//   String sistema()                                            versão e recursos da CPU (para o "Testar a velocidade")
#include <jni.h>

#include <atomic>
#include <cstdio>
#include <string>

#include "whisper.h"

#ifdef __ANDROID__
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "OrbitaWhisper", __VA_ARGS__)
#else
#define LOGI(...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } while (0)
#endif

static std::atomic<bool> g_abortar(false);

struct Progresso {
    JNIEnv * env;
    jobject obj;
    jmethodID metodo;
    int ultimo;
};

static void ao_progresso(struct whisper_context *, struct whisper_state *, int pct, void * dados) {
    auto * p = static_cast<Progresso *>(dados);
    pct = pct < 0 ? 0 : pct > 100 ? 100 : pct;
    if (!p || !p->obj || !p->metodo || pct == p->ultimo) return;
    p->ultimo = pct;
    p->env->CallVoidMethod(p->obj, p->metodo, (jint) pct);
    if (p->env->ExceptionCheck()) p->env->ExceptionClear();
}

static bool ao_abortar(void *) { return g_abortar.load(); }

// o texto vem em UTF-8 do whisper.cpp; aqui só se escapam aspas, barra e controles (o resto passa como está)
static void json_texto(std::string & s, const char * t) {
    s.push_back('"');
    for (const unsigned char * c = (const unsigned char *) t; c && *c; c++) {
        switch (*c) {
            case '"': s += "\\\""; break;
            case '\\': s += "\\\\"; break;
            case '\n': s += "\\n"; break;
            case '\r': s += "\\r"; break;
            case '\t': s += "\\t"; break;
            default:
                if (*c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", *c); s += b; }
                else s.push_back((char) *c);
        }
    }
    s.push_back('"');
}

static void silencio(enum ggml_log_level, const char *, void *) {}

extern "C" {

JNIEXPORT jlong JNICALL Java_br_alediov_odontoquest_Whisper_iniciar(JNIEnv * env, jclass, jstring jmodelo, jint) {
    whisper_log_set(silencio, nullptr);
    const char * modelo = env->GetStringUTFChars(jmodelo, nullptr);
    whisper_context_params cp = whisper_context_default_params();
    cp.use_gpu = false;      // só a CPU: a GPU dos celulares (Vulkan/OpenCL) varia demais de aparelho para aparelho
    cp.flash_attn = true;    // menos memória e mais rápido na CPU
    whisper_context * ctx = whisper_init_from_file_with_params(modelo, cp);
    LOGI("modelo %s: %s", modelo, ctx ? "carregado" : "falhou");
    env->ReleaseStringUTFChars(jmodelo, modelo);
    return (jlong) (intptr_t) ctx;
}

JNIEXPORT jbyteArray JNICALL Java_br_alediov_odontoquest_Whisper_transcrever(JNIEnv * env, jclass, jlong jctx, jfloatArray jpcm,
        jstring jlingua, jstring jprompt, jint threads, jstring jvad, jobject jprog) {
    auto * ctx = (whisper_context *) (intptr_t) jctx;
    if (!ctx || !jpcm) return nullptr;
    g_abortar.store(false);

    const char * lingua = jlingua ? env->GetStringUTFChars(jlingua, nullptr) : nullptr;
    const char * prompt = jprompt ? env->GetStringUTFChars(jprompt, nullptr) : nullptr;
    const char * vad = jvad ? env->GetStringUTFChars(jvad, nullptr) : nullptr;

    whisper_full_params p = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    p.n_threads = threads > 0 ? threads : 4;
    p.language = (lingua && *lingua) ? lingua : "pt";
    p.translate = false;
    p.print_progress = false;
    p.print_realtime = false;
    p.print_special = false;
    p.print_timestamps = false;
    p.no_context = false;              // usa o que já foi dito como contexto (nomes repetidos na aula saem iguais)
    p.suppress_blank = true;
    p.suppress_nst = true;             // sem "[música]", "(risos)" etc.
    if (prompt && *prompt) {
        p.initial_prompt = prompt;     // os termos técnicos da disciplina (glossário): o modelo os escreve certo
        p.carry_initial_prompt = true; // em todas as janelas de 30 s, não só na primeira
    }
    if (vad && *vad) {                 // detecção de voz (Silero): pula os silêncios e evita frases inventadas neles
        p.vad = true;
        p.vad_model_path = vad;
        p.vad_params.min_silence_duration_ms = 500;
        p.vad_params.speech_pad_ms = 200;
    }

    Progresso prog = { env, jprog, nullptr, -1 };
    if (jprog) {
        jclass cls = env->GetObjectClass(jprog);
        prog.metodo = env->GetMethodID(cls, "progresso", "(I)V");
        if (env->ExceptionCheck()) { env->ExceptionClear(); prog.metodo = nullptr; }
        p.progress_callback = ao_progresso;
        p.progress_callback_user_data = &prog;
    }
    p.abort_callback = ao_abortar;
    p.abort_callback_user_data = nullptr;

    jsize n = env->GetArrayLength(jpcm);
    jfloat * pcm = env->GetFloatArrayElements(jpcm, nullptr);
    int r = whisper_full(ctx, p, pcm, n);
    env->ReleaseFloatArrayElements(jpcm, pcm, JNI_ABORT);

    jbyteArray saida = nullptr;
    if (r == 0 && !g_abortar.load()) {
        std::string s = "[";
        const int ns = whisper_full_n_segments(ctx);
        for (int i = 0; i < ns; i++) {
            if (i) s.push_back(',');
            char b[96];
            // t0 e t1 vêm em centésimos de segundo
            snprintf(b, sizeof b, "[%lld,%lld,", (long long) whisper_full_get_segment_t0(ctx, i) * 10, (long long) whisper_full_get_segment_t1(ctx, i) * 10);
            s += b;
            json_texto(s, whisper_full_get_segment_text(ctx, i));
            snprintf(b, sizeof b, ",%.3f]", whisper_full_get_segment_no_speech_prob(ctx, i));
            s += b;
        }
        s.push_back(']');
        saida = env->NewByteArray((jsize) s.size());
        if (saida) env->SetByteArrayRegion(saida, 0, (jsize) s.size(), (const jbyte *) s.data());
    } else {
        LOGI("transcrição %s (%d)", g_abortar.load() ? "interrompida" : "falhou", r);
    }

    if (lingua) env->ReleaseStringUTFChars(jlingua, lingua);
    if (prompt) env->ReleaseStringUTFChars(jprompt, prompt);
    if (vad) env->ReleaseStringUTFChars(jvad, vad);
    return saida;
}

JNIEXPORT void JNICALL Java_br_alediov_odontoquest_Whisper_abortar(JNIEnv *, jclass, jboolean sim) {
    g_abortar.store(sim == JNI_TRUE);
}

JNIEXPORT void JNICALL Java_br_alediov_odontoquest_Whisper_liberar(JNIEnv *, jclass, jlong jctx) {
    auto * ctx = (whisper_context *) (intptr_t) jctx;
    if (ctx) whisper_free(ctx);
}

JNIEXPORT jstring JNICALL Java_br_alediov_odontoquest_Whisper_sistema(JNIEnv * env, jclass) {
    std::string s = std::string("whisper.cpp ") + whisper_version() + " | " + whisper_print_system_info();
    return env->NewStringUTF(s.c_str());
}

}  // extern "C"
