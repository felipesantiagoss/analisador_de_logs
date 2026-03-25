from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
import traceback
from pathlib import Path
from typing import Iterable

PALAVRAS_CHAVE = ("erro", "warning", "info")
CARGA_SIMULADA = 1000
BUFFER_PADRAO = 32

BASE_DIR = Path(__file__).resolve().parent
PROJETO_DIR = BASE_DIR.parent
LOG1_PADRAO = PROJETO_DIR / "log1"
LOG2_PADRAO = PROJETO_DIR / "log2"


def resultado_vazio() -> dict:
    return {
        "linhas": 0,
        "palavras": 0,
        "caracteres": 0,
        "contagem": {chave: 0 for chave in PALAVRAS_CHAVE},
    }


def somar_resultado(destino: dict, origem: dict) -> None:
    destino["linhas"] += origem["linhas"]
    destino["palavras"] += origem["palavras"]
    destino["caracteres"] += origem["caracteres"]

    for chave in PALAVRAS_CHAVE:
        destino["contagem"][chave] += origem["contagem"][chave]


def consolidar_resultados(resultados: Iterable[dict]) -> dict:
    consolidado = resultado_vazio()
    for resultado in resultados:
        somar_resultado(consolidado, resultado)
    return consolidado


def listar_arquivos(pasta: Path | str) -> list[Path]:
    caminho_pasta = Path(pasta)
    if not caminho_pasta.exists():
        raise FileNotFoundError(f"Pasta nao encontrada: {caminho_pasta}")

    arquivos = [item for item in caminho_pasta.iterdir() if item.is_file()]
    return sorted(arquivos)


def processar_arquivo(caminho: Path | str) -> dict:
    totais = resultado_vazio()

    with open(caminho, "r", encoding="utf-8") as arquivo:
        for linha in arquivo:
            palavras = linha.split()

            totais["linhas"] += 1
            totais["palavras"] += len(palavras)
            totais["caracteres"] += len(linha)

            for palavra in palavras:
                if palavra in totais["contagem"]:
                    totais["contagem"][palavra] += 1

            for _ in range(CARGA_SIMULADA):
                pass

    return totais


def executar_serial(pasta: Path | str) -> dict:
    arquivos = listar_arquivos(pasta)
    resultados = []

    inicio = time.perf_counter()

    for arquivo in arquivos:
        resultados.append(processar_arquivo(arquivo))

    tempo_total = time.perf_counter() - inicio
    resumo = consolidar_resultados(resultados)

    return {
        "modo": "serial",
        "processos": 1,
        "buffer": None,
        "arquivos_processados": len(arquivos),
        "tempo_total": tempo_total,
        "resultado": resumo,
    }


def _worker_consumidor(fila_tarefas: mp.Queue, fila_resultados: mp.Queue) -> None:
    acumulado = resultado_vazio()
    arquivos_processados = 0

    try:
        while True:
            caminho = fila_tarefas.get()
            if caminho is None:
                break

            somar_resultado(acumulado, processar_arquivo(caminho))
            arquivos_processados += 1

        fila_resultados.put(
            {
                "tipo": "resultado",
                "arquivos_processados": arquivos_processados,
                "resultado": acumulado,
            }
        )
    except Exception as exc:  
        fila_resultados.put(
            {
                "tipo": "erro",
                "mensagem": str(exc),
                "traceback": traceback.format_exc(),
            }
        )


def obter_contexto_mp() -> mp.context.BaseContext:
    if os.name == "posix":
        return mp.get_context("fork")
    return mp.get_context("spawn")


def executar_paralelo(
    pasta: Path | str,
    processos: int,
    buffer_size: int = BUFFER_PADRAO,
) -> dict:
    if processos < 1:
        raise ValueError("O numero de processos deve ser >= 1.")

    if buffer_size < 1:
        raise ValueError("O tamanho do buffer deve ser >= 1.")

    arquivos = listar_arquivos(pasta)
    contexto = obter_contexto_mp()
    fila_tarefas = contexto.Queue(maxsize=buffer_size)
    fila_resultados = contexto.Queue()
    workers = []

    inicio = time.perf_counter()

    for _ in range(processos):
        worker = contexto.Process(
            target=_worker_consumidor,
            args=(fila_tarefas, fila_resultados),
        )
        worker.start()
        workers.append(worker)

    for arquivo in arquivos:
        fila_tarefas.put(str(arquivo))

    for _ in range(processos):
        fila_tarefas.put(None)

    mensagens = [fila_resultados.get() for _ in range(processos)]

    for worker in workers:
        worker.join()

    tempo_total = time.perf_counter() - inicio

    erros = [mensagem for mensagem in mensagens if mensagem["tipo"] == "erro"]
    if erros:
        detalhes = "\n\n".join(
            f"{erro['mensagem']}\n{erro['traceback']}" for erro in erros
        )
        raise RuntimeError(f"Falha na execucao paralela:\n{detalhes}")

    resumos = [mensagem["resultado"] for mensagem in mensagens]
    total_arquivos = sum(mensagem["arquivos_processados"] for mensagem in mensagens)

    return {
        "modo": "paralelo",
        "processos": processos,
        "buffer": buffer_size,
        "arquivos_processados": total_arquivos,
        "tempo_total": tempo_total,
        "resultado": consolidar_resultados(resumos),
    }


def resultados_iguais(referencia: dict, candidato: dict) -> bool:
    return referencia == candidato


def imprimir_execucao(info_execucao: dict) -> None:
    titulo = "EXECUCAO SERIAL" if info_execucao["modo"] == "serial" else "EXECUCAO PARALELA"

    print(f"\n=== {titulo} ===")
    print(f"Arquivos processados: {info_execucao['arquivos_processados']}")
    if info_execucao["modo"] == "paralelo":
        print(f"Processos: {info_execucao['processos']}")
        print(f"Buffer limitado: {info_execucao['buffer']}")
    print(f"Tempo total: {info_execucao['tempo_total']:.4f} segundos")

    resumo = info_execucao["resultado"]
    print("\n=== RESULTADO CONSOLIDADO ===")
    print(f"Total de linhas: {resumo['linhas']}")
    print(f"Total de palavras: {resumo['palavras']}")
    print(f"Total de caracteres: {resumo['caracteres']}")

    print("\nContagem de palavras-chave:")
    for chave in PALAVRAS_CHAVE:
        print(f"  {chave}: {resumo['contagem'][chave]}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisador serial/paralelo de arquivos de log."
    )
    parser.add_argument(
        "--modo",
        choices=("serial", "paralelo"),
        default="paralelo",
        help="Modo de execucao.",
    )
    parser.add_argument(
        "--pasta",
        type=Path,
        default=LOG1_PADRAO,
        help="Pasta com os arquivos de log.",
    )
    parser.add_argument(
        "--processos",
        type=int,
        default=2,
        help="Numero de processos da execucao paralela.",
    )
    parser.add_argument(
        "--buffer",
        type=int,
        default=BUFFER_PADRAO,
        help="Capacidade do buffer limitado.",
    )
    parser.add_argument(
        "--saida-json",
        type=Path,
        help="Arquivo opcional para salvar o resultado em JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.modo == "serial":
        resultado = executar_serial(args.pasta)
    else:
        resultado = executar_paralelo(
            pasta=args.pasta,
            processos=args.processos,
            buffer_size=args.buffer,
        )

    imprimir_execucao(resultado)

    if args.saida_json:
        args.saida_json.parent.mkdir(parents=True, exist_ok=True)
        args.saida_json.write_text(
            json.dumps(resultado, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    mp.freeze_support()
    main()
