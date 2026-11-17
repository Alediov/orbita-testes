package br.alediov.odontoquest;

import java.io.BufferedReader;
import java.io.FileReader;

/**
 * Ponte com o llama.cpp (MIT) para a Eva conversar com um modelo pequeno no próprio celular, sem internet
 * (docs/plano-eva-local.md). A biblioteca nativa (tools/eva-local/llama-jni/orbita_llama.cpp) é compilada uma vez pelo
 * workflow manual "Llama (IA local da Eva)" e fica em android-extra/jniLibs/arm64-v8a/ em duas variantes, como a do
 * Whisper: a comum (armv8-a) e a rápida (armv8.2-a com dotprod e fp16), escolhida pelo /proc/cpuinfo.
 * Sem a biblioteca (workflow ainda não rodado, ou aparelho de 32 bits), `carregar` devolve false e o app avisa.
 * Só usa classes do Java puro, para dar para testar no notebook (tools/eva-local/llama-jni/teste_x86.sh).
 */
final class Llama {
    /** Cada pedaço da resposta (UTF-8 inteiro, sem cortar acento); devolver false para parar. */
    interface Pedacos { boolean pedaco(byte[] utf8); }

    private static String carregada = null, erro = null;

    static synchronized boolean carregar() {
        if (carregada != null) return true;
        if (erro != null) return false;
        String[] ordem = Whisper.cpuRapida() ? new String[] { "orbita_llama_v82", "orbita_llama" } : new String[] { "orbita_llama" };
        for (String nome : ordem) {
            try {
                System.loadLibrary(nome);
                carregada = nome;
                return true;
            } catch (Throwable t) {
                erro = String.valueOf(t.getMessage());
            }
        }
        return false;
    }

    static synchronized String variante() { return carregada; }
    static synchronized String erroDeCarga() { return erro; }

    /** Núcleos para o modelo: os grandes (no Exynos 1380, os 4 Cortex-A78). Com os pequenos junto ele fica mais lento. */
    static int threads() {
        int n = Runtime.getRuntime().availableProcessors();
        return Math.max(1, Math.min(4, n <= 4 ? n : n / 2));
    }

    /** Lê "Features" do /proc/cpuinfo (para o "Testar"): dotprod, i8mm, fp16… */
    static String recursos() {
        try (BufferedReader r = new BufferedReader(new FileReader("/proc/cpuinfo"))) {
            String l;
            while ((l = r.readLine()) != null) if (l.toLowerCase().startsWith("features")) return l.substring(l.indexOf(':') + 1).trim();
        } catch (Exception e) { /* sem cpuinfo */ }
        return "";
    }

    static native long abrir(String modelo, int threads, int nCtx);
    /** JSON em UTF-8: {texto, fim, erro?, n_prompt, n_reuso, n_gerados, ms_prompt, ms_gerar}. */
    static native byte[] gerar(long h, String[] papeis, String[] textos, String fixo, String sufixo, int maxTokens,
                               float temp, float topP, int topK, float presenca, int semente, Pedacos p);
    static native void parar(boolean sim);
    static native void liberar(long h);
    static native String sistema();
}
