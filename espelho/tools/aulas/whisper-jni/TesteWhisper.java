package br.alediov.odontoquest;

import java.io.DataInputStream;
import java.io.FileInputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

/** Confere a ponte JNI (Whisper.java + orbita_whisper.cpp) no notebook: java TesteWhisper <modelo> <wav 16 kHz mono> */
public class TesteWhisper {
    public static void main(String[] a) throws Exception {
        if (!Whisper.carregar()) throw new RuntimeException("biblioteca: " + Whisper.erroDeCarga());
        System.out.println("variante: " + Whisper.variante() + " | " + Whisper.sistema());
        long ctx = Whisper.iniciar(a[0], 2);
        System.out.println("contexto: " + (ctx != 0 ? "ok" : "0 (modelo não abriu)"));
        if (ctx == 0) return;
        byte[] wav = new FileInputStream(a[1]).readAllBytes();
        ByteBuffer b = ByteBuffer.wrap(wav, 44, wav.length - 44).order(ByteOrder.LITTLE_ENDIAN);
        float[] pcm = new float[(wav.length - 44) / 2];
        for (int i = 0; i < pcm.length; i++) pcm[i] = b.getShort() / 32768f;
        long t = System.currentTimeMillis();
        byte[] r = Whisper.transcrever(ctx, pcm, "pt", "Aula de Anestesiologia. Termos: nervo alveolar inferior, articaína.", 2, null, p -> System.out.print(p + "% "));
        System.out.println("\nsegundos: " + (System.currentTimeMillis() - t) / 1000.0);
        System.out.println(r == null ? "null" : new String(r, StandardCharsets.UTF_8));
        Whisper.liberar(ctx);
    }
}
