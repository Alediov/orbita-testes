package br.alediov.odontoquest;

import java.io.BufferedReader;
import java.io.FileReader;

/**
 * Ponte com o whisper.cpp (MIT) para transcrever as aulas gravadas no próprio celular (docs/plano-gravacao.md).
 * A biblioteca nativa (tools/aulas/whisper-jni/orbita_whisper.cpp) é compilada uma vez pelo workflow manual
 * "Whisper (transcrição das aulas)" e fica em android-extra/jniLibs/arm64-v8a/ em duas variantes: a comum (armv8-a) e
 * a rápida (armv8.2-a com dotprod e fp16, a dos celulares de 2018 para cá), escolhida pelo /proc/cpuinfo.
 * Sem a biblioteca (workflow ainda não rodado, ou aparelho de 32 bits), `carregar` devolve false e o app avisa.
 * Só usa classes do Java puro, para dar para testar no notebook (tools/aulas/whisper-jni/teste_x86.sh).
 */
final class Whisper {
    interface Progresso { void progresso(int pct); }

    private static String carregada = null, erro = null;

    /** Carrega a biblioteca (uma vez). Devolve true se o motor está disponível. */
    static synchronized boolean carregar() {
        if (carregada != null) return true;
        if (erro != null) return false;
        String[] ordem = cpuRapida() ? new String[] { "orbita_whisper_v82", "orbita_whisper" } : new String[] { "orbita_whisper" };
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

    /** dotprod (asimddp) e meia precisão (asimdhp/fphp): a variante armv8.2-a roda até ~2× mais rápido. */
    static boolean cpuRapida() {
        try (BufferedReader r = new BufferedReader(new FileReader("/proc/cpuinfo"))) {
            String l;
            boolean dp = false, hp = false;
            while ((l = r.readLine()) != null) {
                if (!l.toLowerCase().startsWith("features")) continue;
                if (l.contains("asimddp")) dp = true;
                if (l.contains("asimdhp") || l.contains("fphp")) hp = true;
            }
            return dp && hp;
        } catch (Exception e) {
            return false;
        }
    }

    /** Núcleos para o whisper: os rápidos (até 4); com mais threads que núcleos grandes ele fica mais lento. */
    static int threads() {
        int n = Runtime.getRuntime().availableProcessors();
        return Math.max(1, Math.min(4, n <= 4 ? n : n / 2));
    }

    static native long iniciar(String modelo, int threads);
    /** JSON em UTF-8: [[ini_ms, fim_ms, "texto", prob_sem_fala], ...]; null se falhou ou foi interrompido. */
    static native byte[] transcrever(long ctx, float[] pcm, String lingua, String prompt, int threads, String vad, Progresso p);
    static native void abortar(boolean sim);
    static native void liberar(long ctx);
    static native String sistema();
}
