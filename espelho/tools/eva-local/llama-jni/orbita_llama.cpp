// Ponte JNI entre o Órbita (Llama.java) e o llama.cpp (MIT), para a Eva conversar com um modelo pequeno no próprio
// celular, sem internet (IA local da Eva, docs/plano-eva-local.md). Compilado para arm64-v8a pelo workflow manual
// .github/workflows/llama.yml, que guarda as bibliotecas prontas em android-extra/jniLibs/arm64-v8a/; no notebook,
// tools/eva-local/llama-jni/teste_x86.sh compila para x86 só para conferir esta ponte.
//
// Métodos (classe br.alediov.odontoquest.Llama; uma chamada por vez, numa thread que não é a da tela):
//   long   abrir(String modelo, int threads, int nCtx)             estado (0 se falhou)
//   byte[] gerar(long h, String[] papeis, String[] textos, String fixo, String sufixo, int maxTokens, float temp,
//                float topP, int topK, float presenca, int semente, Pedacos p)
//          → JSON em UTF-8: {"texto", "fim" (eog|limite|parado|erro), "erro"?, "n_prompt", "n_reuso", "n_gerados",
//            "ms_prompt", "ms_gerar"} (null só se faltou memória para a resposta)
//   void   parar(boolean sim)                                       pede para parar a geração em andamento
//   void   liberar(long h)
//   String sistema()                                                recursos da CPU (para o "Testar")
//
// O pedido vai pelo modelo de conversa do próprio arquivo GGUF (llama_chat_apply_template; sem ele, chatml) e o
// `sufixo` entra depois da abertura da resposta (o Qwen 3.5 sem raciocínio: "<think>\n\n</think>\n\n").
// Reaproveitamento: o que já está na memória (o começo igual ao pedido anterior) não é recalculado; nos modelos
// híbridos (o Qwen 3.5 tem camadas recorrentes, que não deixam apagar só o fim), guarda-se uma cópia do estado logo
// depois da parte fixa (`fixo`, o jeito da Eva), e cada pedido recomeça dela.
#include <jni.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "llama.h"

#ifdef __ANDROID__
#include <android/log.h>
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, "OrbitaLlama", __VA_ARGS__)
#else
#define LOGI(...) do { fprintf(stderr, __VA_ARGS__); fputc('\n', stderr); } while (0)
#endif

static std::atomic<bool> g_parar(false);

struct Estado {
    llama_model * model = nullptr;
    llama_context * ctx = nullptr;
    const llama_vocab * vocab = nullptr;
    std::string tmpl;                        // o modelo de conversa do GGUF (vazio: chatml)
    std::vector<llama_token> mem;            // os tokens que estão na memória do contexto agora (sequência 0)
    std::vector<llama_token> snap_toks;      // a cópia do estado depois da parte fixa
    std::vector<uint8_t> snap;
};

static void ao_log(enum ggml_log_level nivel, const char * texto, void *) {
    if (nivel == GGML_LOG_LEVEL_ERROR && texto) LOGI("%s", texto);
}
static bool ao_abortar(void *) { return g_parar.load(); }

static long long agora_ms() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

static void json_texto(std::string & s, const std::string & t) {
    s.push_back('"');
    for (unsigned char c : t) {
        switch (c) {
            case '"': s += "\\\""; break;
            case '\\': s += "\\\\"; break;
            case '\n': s += "\\n"; break;
            case '\r': s += "\\r"; break;
            case '\t': s += "\\t"; break;
            default:
                if (c < 0x20) { char b[8]; snprintf(b, sizeof b, "\\u%04x", c); s += b; }
                else s.push_back((char) c);
        }
    }
    s.push_back('"');
}

// quantos bytes do começo de `s` terminam num caractere UTF-8 completo (para mandar os pedaços sem cortar um acento)
static size_t utf8_inteiro(const std::string & s) {
    size_t n = s.size();
    for (size_t volta = 1; volta <= 4 && volta <= n; volta++) {
        unsigned char c = (unsigned char) s[n - volta];
        if ((c & 0xC0) == 0x80) continue;                 // byte do meio
        size_t precisa = c < 0x80 ? 1 : (c & 0xE0) == 0xC0 ? 2 : (c & 0xF0) == 0xE0 ? 3 : (c & 0xF8) == 0xF0 ? 4 : 1;
        return volta >= precisa ? n : n - volta;
    }
    return n;
}

static std::vector<llama_token> tokenizar(const llama_vocab * vocab, const std::string & texto) {
    std::vector<llama_token> t(texto.size() + 16);
    int n = llama_tokenize(vocab, texto.c_str(), (int32_t) texto.size(), t.data(), (int32_t) t.size(), true, true);
    if (n < 0) {
        t.resize(-n);
        n = llama_tokenize(vocab, texto.c_str(), (int32_t) texto.size(), t.data(), (int32_t) t.size(), true, true);
    }
    t.resize(n > 0 ? n : 0);
    return t;
}

static bool formatar(const Estado * e, const std::vector<llama_chat_message> & msgs, bool abrir_resposta, std::string & saida) {
    size_t total = 0;
    for (auto & m : msgs) total += strlen(m.content) + 64;
    for (int tentativa = 0; tentativa < 2; tentativa++) {
        const char * tmpl = (tentativa == 0 && !e->tmpl.empty()) ? e->tmpl.c_str() : "chatml";
        std::vector<char> buf(total * 2 + 1024);
        int n = llama_chat_apply_template(tmpl, msgs.data(), msgs.size(), abrir_resposta, buf.data(), (int32_t) buf.size());
        if (n > (int) buf.size()) {
            buf.resize(n + 1);
            n = llama_chat_apply_template(tmpl, msgs.data(), msgs.size(), abrir_resposta, buf.data(), (int32_t) buf.size());
        }
        if (n >= 0) { saida.assign(buf.data(), n); return true; }
        if (e->tmpl.empty()) break;
    }
    return false;
}

static int decodificar(Estado * e, const std::vector<llama_token> & toks, size_t de, size_t ate, int n_batch) {
    for (size_t i = de; i < ate; i += n_batch) {
        int32_t n = (int32_t) std::min<size_t>(n_batch, ate - i);
        llama_batch b = llama_batch_get_one(const_cast<llama_token *>(toks.data()) + i, n);
        int r = llama_decode(e->ctx, b);
        if (r != 0) return r;
        e->mem.insert(e->mem.end(), toks.begin() + i, toks.begin() + i + n);
    }
    return 0;
}

static void esquecer(Estado * e) {
    llama_memory_clear(llama_get_memory(e->ctx), true);
    e->mem.clear();
}

static bool comeca_com(const std::vector<llama_token> & a, const std::vector<llama_token> & prefixo) {
    return !prefixo.empty() && prefixo.size() <= a.size() && std::equal(prefixo.begin(), prefixo.end(), a.begin());
}

extern "C" {

JNIEXPORT jlong JNICALL Java_br_alediov_odontoquest_Llama_abrir(JNIEnv * env, jclass, jstring jmodelo, jint threads, jint n_ctx) {
    static bool iniciado = false;
    if (!iniciado) { llama_log_set(ao_log, nullptr); llama_backend_init(); iniciado = true; }
    const char * caminho = env->GetStringUTFChars(jmodelo, nullptr);
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 0;    // só a CPU: a GPU dos celulares (Vulkan/OpenCL) varia demais de aparelho para aparelho
    llama_model * model = llama_model_load_from_file(caminho, mp);
    LOGI("modelo %s: %s", caminho, model ? "carregado" : "falhou");
    env->ReleaseStringUTFChars(jmodelo, caminho);
    if (!model) return 0;

    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = n_ctx > 0 ? (uint32_t) n_ctx : 3072;
    cp.n_batch = 512;
    cp.n_ubatch = 512;
    cp.n_seq_max = 1;
    cp.n_threads = threads > 0 ? threads : 4;
    cp.n_threads_batch = cp.n_threads;
    cp.flash_attn_type = LLAMA_FLASH_ATTN_TYPE_AUTO;
    cp.no_perf = true;
    cp.abort_callback = ao_abortar;
    cp.abort_callback_data = nullptr;
    llama_context * ctx = llama_init_from_model(model, cp);
    if (!ctx) { LOGI("contexto falhou"); llama_model_free(model); return 0; }

    auto * e = new Estado();
    e->model = model;
    e->ctx = ctx;
    e->vocab = llama_model_get_vocab(model);
    const char * t = llama_model_chat_template(model, nullptr);
    if (t) e->tmpl = t;
    return (jlong) (intptr_t) e;
}

JNIEXPORT jbyteArray JNICALL Java_br_alediov_odontoquest_Llama_gerar(JNIEnv * env, jclass, jlong h, jobjectArray jpapeis,
        jobjectArray jtextos, jstring jfixo, jstring jsufixo, jint max_tokens, jfloat temp, jfloat top_p, jint top_k,
        jfloat presenca, jint semente, jobject jcb) {
    auto * e = (Estado *) (intptr_t) h;
    std::string erro, fim = "erro", texto;
    int n_prompt = 0, n_reuso = 0, n_gerados = 0;
    long long ms_prompt = 0, ms_gerar = 0;
    g_parar.store(false);

    // as mensagens (cópias em std::string: os ponteiros do JNI são soltos logo)
    std::vector<std::string> papeis, textos;
    const jsize n = (jpapeis && jtextos) ? std::min(env->GetArrayLength(jpapeis), env->GetArrayLength(jtextos)) : 0;
    for (jsize i = 0; i < n; i++) {
        auto jp = (jstring) env->GetObjectArrayElement(jpapeis, i), jt = (jstring) env->GetObjectArrayElement(jtextos, i);
        const char * p = jp ? env->GetStringUTFChars(jp, nullptr) : "user";
        const char * t = jt ? env->GetStringUTFChars(jt, nullptr) : "";
        papeis.emplace_back(p); textos.emplace_back(t);
        if (jp) { env->ReleaseStringUTFChars(jp, p); env->DeleteLocalRef(jp); }
        if (jt) { env->ReleaseStringUTFChars(jt, t); env->DeleteLocalRef(jt); }
    }
    std::string fixo, sufixo;
    if (jfixo) { const char * s = env->GetStringUTFChars(jfixo, nullptr); fixo = s; env->ReleaseStringUTFChars(jfixo, s); }
    if (jsufixo) { const char * s = env->GetStringUTFChars(jsufixo, nullptr); sufixo = s; env->ReleaseStringUTFChars(jsufixo, s); }

    jmethodID metodo = nullptr;
    if (jcb) {
        metodo = env->GetMethodID(env->GetObjectClass(jcb), "pedaco", "([B)Z");
        if (env->ExceptionCheck()) { env->ExceptionClear(); metodo = nullptr; }
    }

    llama_sampler * smpl = nullptr;
    do {
        if (!e || !e->ctx) { erro = "sem modelo"; break; }
        if (papeis.empty()) { erro = "sem mensagens"; break; }

        std::vector<llama_chat_message> msgs;
        for (size_t i = 0; i < papeis.size(); i++) msgs.push_back({ papeis[i].c_str(), textos[i].c_str() });
        std::string prompt;
        if (!formatar(e, msgs, true, prompt)) { erro = "modelo de conversa"; break; }
        prompt += sufixo;
        std::vector<llama_token> toks = tokenizar(e->vocab, prompt);
        n_prompt = (int) toks.size();
        const int n_ctx = (int) llama_n_ctx(e->ctx);
        if (toks.empty()) { erro = "pedido vazio"; break; }
        if ((int) toks.size() + std::max(16, (int) max_tokens) > n_ctx) { erro = "pedido longo demais"; break; }

        // a parte fixa: os tokens do começo que não mudam de um pedido para outro (sem os últimos, que podem se juntar
        // de outro jeito com o que vem depois dela)
        std::vector<llama_token> fixos;
        if (!fixo.empty()) {
            std::vector<llama_chat_message> so = { { papeis[0].c_str(), fixo.c_str() } };
            std::string pf;
            if (formatar(e, so, false, pf)) {
                fixos = tokenizar(e->vocab, pf);
                fixos.resize(fixos.size() > 24 ? fixos.size() - 8 : 0);
                if (!comeca_com(toks, fixos)) fixos.clear();
            }
        }

        // o que já está na memória
        llama_memory_t memoria = llama_get_memory(e->ctx);
        size_t comum = 0;
        while (comum < e->mem.size() && comum < toks.size() && e->mem[comum] == toks[comum]) comum++;
        if (comum >= toks.size()) comum = toks.size() - 1;   // o último sempre se calcula de novo (dá a 1ª palavra)
        const bool snap_ok = !e->snap.empty() && comeca_com(toks, e->snap_toks) && e->snap_toks.size() < toks.size();
        bool pronto = false;
#ifdef ORBITA_TESTE_RECORRENTE
        const bool apaga_fim = false;   // teste no x86: faz de conta que a memória é recorrente (como a do Qwen 3.5)
#else
        const bool apaga_fim = true;
#endif
        if (apaga_fim && comum > 0 && (!snap_ok || comum >= e->snap_toks.size()) && llama_memory_seq_rm(memoria, 0, (llama_pos) comum, -1)) {
            e->mem.resize(comum);
            pronto = true;
        }
        if (!pronto && snap_ok) {
            esquecer(e);
            if (llama_state_seq_set_data(e->ctx, e->snap.data(), e->snap.size(), 0) > 0) { e->mem = e->snap_toks; pronto = true; }
            else { esquecer(e); e->snap.clear(); e->snap_toks.clear(); }
        }
        if (!pronto) esquecer(e);
        n_reuso = (int) e->mem.size();

        // o pedido: até o fim da parte fixa (e a cópia do estado ali, se ainda não há), depois o resto
        long long t0 = agora_ms();
        int r = 0;
        const int n_batch = 512;
        if (!fixos.empty() && e->mem.size() < fixos.size() && !(snap_ok && e->snap_toks == fixos)) {
            r = decodificar(e, toks, e->mem.size(), fixos.size(), n_batch);
            if (r == 0) {
                size_t tam = llama_state_seq_get_size(e->ctx, 0);
                e->snap.resize(tam);
                if (tam && llama_state_seq_get_data(e->ctx, e->snap.data(), tam, 0) == tam) e->snap_toks = fixos;
                else { e->snap.clear(); e->snap_toks.clear(); }
            }
        }
        if (r == 0) r = decodificar(e, toks, e->mem.size(), toks.size(), n_batch);
        ms_prompt = agora_ms() - t0;
        if (r != 0) {
            esquecer(e);
            if (r == 2 || g_parar.load()) fim = "parado"; else erro = "decode " + std::to_string(r);
            break;
        }

        // a resposta
        llama_sampler_chain_params sp = llama_sampler_chain_default_params();
        sp.no_perf = true;
        smpl = llama_sampler_chain_init(sp);
        if (temp <= 0.0f) {
            llama_sampler_chain_add(smpl, llama_sampler_init_greedy());
        } else {
            llama_sampler_chain_add(smpl, llama_sampler_init_top_k(top_k > 0 ? top_k : 40));
            if (presenca > 0.0f) llama_sampler_chain_add(smpl, llama_sampler_init_penalties(llama_vocab_n_tokens(e->vocab), 64, 1.0f, 0.0f, presenca));
            llama_sampler_chain_add(smpl, llama_sampler_init_top_p(top_p > 0.0f && top_p <= 1.0f ? top_p : 0.9f, 1));
            llama_sampler_chain_add(smpl, llama_sampler_init_min_p(0.05f, 1));
            llama_sampler_chain_add(smpl, llama_sampler_init_temp(temp));
            llama_sampler_chain_add(smpl, llama_sampler_init_dist((uint32_t) semente));
        }
        t0 = agora_ms();
        size_t mandado = 0;
        fim = "limite";
        for (int i = 0; i < max_tokens; i++) {
            if (g_parar.load()) { fim = "parado"; break; }
            if ((int) e->mem.size() + 1 >= n_ctx) break;
            llama_token tok = llama_sampler_sample(smpl, e->ctx, -1);
            if (llama_vocab_is_eog(e->vocab, tok)) { fim = "eog"; break; }
            char buf[256];
            int np = llama_token_to_piece(e->vocab, tok, buf, sizeof buf, 0, false);
            if (np > 0) texto.append(buf, np);
            n_gerados++;
            // marcas de conversa que um modelo pequeno às vezes escreve como texto: param a resposta
            size_t corte = std::string::npos;
            for (const char * m : { "<|im_start|>", "<|im_end|>", "<end_of_turn>", "<start_of_turn>", "<|eot_id|>" }) {
                size_t p = texto.find(m);
                if (p != std::string::npos) corte = std::min(corte, p);
            }
            if (corte != std::string::npos) { texto.resize(corte); fim = "eog"; break; }
            if (metodo) {
                size_t ate = utf8_inteiro(texto);
                if (ate > mandado) {
                    jbyteArray b = env->NewByteArray((jsize) (ate - mandado));
                    if (b) {
                        env->SetByteArrayRegion(b, 0, (jsize) (ate - mandado), (const jbyte *) texto.data() + mandado);
                        jboolean segue = env->CallBooleanMethod(jcb, metodo, b);
                        env->DeleteLocalRef(b);
                        if (env->ExceptionCheck()) { env->ExceptionClear(); segue = JNI_TRUE; }
                        mandado = ate;
                        if (!segue) { fim = "parado"; break; }
                    }
                }
            }
            llama_batch b1 = llama_batch_get_one(&tok, 1);
            int rd = llama_decode(e->ctx, b1);
            if (rd != 0) {
                esquecer(e);
                if (rd == 2 || g_parar.load()) fim = "parado"; else { fim = "erro"; erro = "decode " + std::to_string(rd); }
                break;
            }
            e->mem.push_back(tok);
        }
        ms_gerar = agora_ms() - t0;
    } while (false);
    if (smpl) llama_sampler_free(smpl);

    std::string s = "{\"texto\":";
    json_texto(s, texto);
    s += ",\"fim\":\"" + fim + "\"";
    if (!erro.empty()) { s += ",\"erro\":"; json_texto(s, erro); }
    char b[200];
    snprintf(b, sizeof b, ",\"n_prompt\":%d,\"n_reuso\":%d,\"n_gerados\":%d,\"ms_prompt\":%lld,\"ms_gerar\":%lld}", n_prompt, n_reuso, n_gerados, ms_prompt, ms_gerar);
    s += b;
    jbyteArray saida = env->NewByteArray((jsize) s.size());
    if (saida) env->SetByteArrayRegion(saida, 0, (jsize) s.size(), (const jbyte *) s.data());
    return saida;
}

JNIEXPORT void JNICALL Java_br_alediov_odontoquest_Llama_parar(JNIEnv *, jclass, jboolean sim) {
    g_parar.store(sim == JNI_TRUE);
}

JNIEXPORT void JNICALL Java_br_alediov_odontoquest_Llama_liberar(JNIEnv *, jclass, jlong h) {
    auto * e = (Estado *) (intptr_t) h;
    if (!e) return;
    if (e->ctx) llama_free(e->ctx);
    if (e->model) llama_model_free(e->model);
    delete e;
}

JNIEXPORT jstring JNICALL Java_br_alediov_odontoquest_Llama_sistema(JNIEnv * env, jclass) {
    std::string s = std::string("llama.cpp | ") + llama_print_system_info();
    return env->NewStringUTF(s.c_str());
}

}  // extern "C"
