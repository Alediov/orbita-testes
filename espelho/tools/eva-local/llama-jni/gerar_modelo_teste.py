"""Monta um GGUF minúsculo (arquitetura llama, pesos aleatórios) com o vocabulário de um ggml-vocab-*.gguf do llama.cpp,
só para conferir a ponte JNI da IA local da Eva no notebook (teste_x86.sh). A resposta sai sem sentido.
Uso: PYTHONPATH=<llama.cpp>/gguf-py python3 gerar_modelo_teste.py <ggml-vocab-qwen2.gguf> <saida.gguf>
"""
import sys

import numpy as np
import gguf

vocab_path, saida = sys.argv[1], sys.argv[2]
r = gguf.GGUFReader(vocab_path)
w = gguf.GGUFWriter(saida, "llama")
n_vocab = 0
for nome, campo in r.fields.items():
    if not nome.startswith("tokenizer.") or not campo.types:
        continue
    tipo = campo.types[0]
    if tipo == gguf.GGUFValueType.ARRAY:
        valor = campo.contents()
        w.add_key_value(nome, valor, tipo, sub_type=campo.types[-1])
        if nome == "tokenizer.ggml.tokens":
            n_vocab = len(valor)
    else:
        w.add_key_value(nome, campo.contents(), tipo)
# um modelo de conversa em ChatML, como o do Qwen (se o vocabulário não trouxer um)
if "tokenizer.chat_template" not in r.fields:
    w.add_key_value("tokenizer.chat_template", "{% for m in messages %}<|im_start|>{{ m.role }}\n{{ m.content }}<|im_end|>\n{% endfor %}{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}", gguf.GGUFValueType.STRING)

D, F, L, H, KV = 64, 128, 2, 4, 2
w.add_context_length(2048)
w.add_embedding_length(D)
w.add_feed_forward_length(F)
w.add_block_count(L)
w.add_head_count(H)
w.add_head_count_kv(KV)
w.add_layer_norm_rms_eps(1e-6)
w.add_rope_freq_base(10000.0)
w.add_rope_dimension_count(D // H)
w.add_vocab_size(n_vocab)
w.add_file_type(gguf.LlamaFileType.ALL_F32)

rng = np.random.default_rng(1)
t = lambda *forma: (rng.standard_normal(forma) * 0.05).astype(np.float32)  # noqa: E731
w.add_tensor("token_embd.weight", t(n_vocab, D))
w.add_tensor("output_norm.weight", np.ones(D, dtype=np.float32))
w.add_tensor("output.weight", t(n_vocab, D))
hd = D // H
for i in range(L):
    p = f"blk.{i}."
    w.add_tensor(p + "attn_norm.weight", np.ones(D, dtype=np.float32))
    w.add_tensor(p + "attn_q.weight", t(D, D))
    w.add_tensor(p + "attn_k.weight", t(KV * hd, D))
    w.add_tensor(p + "attn_v.weight", t(KV * hd, D))
    w.add_tensor(p + "attn_output.weight", t(D, D))
    w.add_tensor(p + "ffn_norm.weight", np.ones(D, dtype=np.float32))
    w.add_tensor(p + "ffn_gate.weight", t(F, D))
    w.add_tensor(p + "ffn_up.weight", t(F, D))
    w.add_tensor(p + "ffn_down.weight", t(D, F))
w.write_header_to_file()
w.write_kv_data_to_file()
w.write_tensors_to_file()
w.close()
print(f"{saida}: vocabulário {n_vocab}, {L} camadas de {D}")
