package br.alediov.odontoquest;

import java.nio.charset.StandardCharsets;

/** Confere a ponte JNI (Llama.java + orbita_llama.cpp) no notebook: java TesteLlama <modelo.gguf> */
public class TesteLlama {
    static String json(byte[] b) { return b == null ? "null" : new String(b, StandardCharsets.UTF_8); }

    public static void main(String[] a) throws Exception {
        if (!Llama.carregar()) throw new RuntimeException("biblioteca: " + Llama.erroDeCarga());
        System.out.println("variante: " + Llama.variante() + " | " + Llama.sistema());
        long h = Llama.abrir(a[0], 2, 1024);
        System.out.println("estado: " + (h != 0 ? "ok" : "0 (modelo não abriu)"));
        if (h == 0) System.exit(1);
        String fixo = "Você é a Eva, companheira de rotina e estudos do Alediov. Responda em português do Brasil, em até três frases curtas e carinhosas.";
        String[] papeis = { "system", "user" };
        StringBuilder pedacos = new StringBuilder();
        int[] n = { 0 };
        for (int i = 0; i < 3; i++) {
            String[] textos = { fixo + "\n\nResumo do dia:\nAgora: segunda, " + (10 + i) + "h.", "Oi, Eva! Tudo bem? (" + i + ")" };
            long t = System.currentTimeMillis();
            String r = json(Llama.gerar(h, papeis, textos, fixo, "", 24, 0.7f, 0.9f, 40, 0.3f, 42 + i, (b) -> { n[0]++; pedacos.append(new String(b, StandardCharsets.UTF_8)); return true; }));
            System.out.println("pedido " + i + " (" + (System.currentTimeMillis() - t) + " ms): " + r);
            if (!r.contains("\"fim\":\"limite\"") && !r.contains("\"fim\":\"eog\"")) throw new RuntimeException("fim inesperado");
            if (i > 0 && !r.matches(".*\"n_reuso\":[1-9].*")) throw new RuntimeException("não reaproveitou a parte fixa");
        }
        System.out.println("pedaços recebidos: " + n[0]);
        // parar pelo retorno do pedaço
        String r = json(Llama.gerar(h, papeis, new String[] { fixo, "Conta uma história." }, fixo, "", 50, 0.7f, 0.9f, 40, 0f, 7, (b) -> false));
        System.out.println("parado pelo pedaço: " + r);
        if (!r.contains("\"fim\":\"parado\"")) throw new RuntimeException("não parou");
        // pedido longo demais para o contexto
        String longo = "palavra ".repeat(3000);
        r = json(Llama.gerar(h, papeis, new String[] { fixo, longo }, fixo, "", 50, 0.7f, 0.9f, 40, 0f, 7, null));
        System.out.println("longo: " + r.substring(0, Math.min(160, r.length())));
        if (!r.contains("longo demais")) throw new RuntimeException("não recusou o pedido longo");
        // de novo depois do erro (a memória continua certa)
        r = json(Llama.gerar(h, papeis, new String[] { fixo, "Oi" }, fixo, "<think>\n\n</think>\n\n", 8, 0f, 1f, 1, 0f, 1, null));
        System.out.println("depois: " + r);
        Llama.liberar(h);
        System.out.println("ok");
    }
}
