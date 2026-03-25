from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import statistics
import subprocess
from datetime import datetime
from pathlib import Path

from analisador_logs import (
    BASE_DIR,
    BUFFER_PADRAO,
    LOG2_PADRAO,
    executar_paralelo,
    executar_serial,
    listar_arquivos,
    resultados_iguais,
)
from graficos_png import gerar_grafico_linhas, paleta_graficos


def _comando_texto(comando: list[str]) -> str | None:
    try:
        return subprocess.check_output(
            comando,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def coletar_ambiente() -> dict:
    hardware = _comando_texto(["system_profiler", "SPHardwareDataType"]) or ""
    so_nome = _comando_texto(["sw_vers", "-productName"])
    so_versao = _comando_texto(["sw_vers", "-productVersion"])

    def extrair(campo: str) -> str | None:
        padrao = rf"{re.escape(campo)}:\s+(.+)"
        encontrado = re.search(padrao, hardware)
        return encontrado.group(1).strip() if encontrado else None

    return {
        "processador": extrair("Chip") or platform.processor() or "Nao identificado",
        "nucleos_fisicos": extrair("Total Number of Cores") or "Nao identificado",
        "nucleos_logicos": str(os.cpu_count()),
        "memoria_ram": extrair("Memory") or "Nao identificado",
        "sistema_operacional": (
            f"{so_nome} {so_versao}" if so_nome and so_versao else platform.platform()
        ),
        "linguagem": "Python",
        "biblioteca_paralelizacao": "multiprocessing (stdlib)",
        "versao_python": platform.python_version(),
    }


def executar_benchmark(
    pasta: Path,
    repeticoes: int,
    processos: list[int],
    buffer_size: int,
) -> dict:
    if repeticoes < 1:
        raise ValueError("O numero de repeticoes deve ser >= 1.")

    tempos_por_config = []
    referencia = None

    for quantidade_processos in [1, *processos]:
        tempos = []
        resultado_referencia_config = None

        for repeticao in range(1, repeticoes + 1):
            if quantidade_processos == 1:
                execucao = executar_serial(pasta)
            else:
                execucao = executar_paralelo(
                    pasta=pasta,
                    processos=quantidade_processos,
                    buffer_size=buffer_size,
                )

            tempos.append(execucao["tempo_total"])

            if referencia is None:
                referencia = execucao["resultado"]
            elif not resultados_iguais(referencia, execucao["resultado"]):
                raise RuntimeError(
                    "O resultado consolidado mudou entre as execucoes. "
                    "A implementacao nao preservou a corretude."
                )

            resultado_referencia_config = execucao["resultado"]
            print(
                f"[{quantidade_processos} processo(s)] "
                f"execucao {repeticao}/{repeticoes}: {execucao['tempo_total']:.4f}s"
            )

        media_tempo = statistics.mean(tempos)
        desvio = statistics.stdev(tempos) if len(tempos) > 1 else 0.0

        tempos_por_config.append(
            {
                "processos": quantidade_processos,
                "tempos": tempos,
                "media_tempo": media_tempo,
                "desvio_padrao": desvio,
                "resultado": resultado_referencia_config,
            }
        )

    tempo_serial = tempos_por_config[0]["media_tempo"]

    for item in tempos_por_config:
        speedup = tempo_serial / item["media_tempo"]
        item["speedup"] = speedup
        item["eficiencia"] = speedup / item["processos"]

    return {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "pasta_logs": str(pasta.resolve()),
        "total_arquivos": len(listar_arquivos(pasta)),
        "buffer_size": buffer_size,
        "repeticoes": repeticoes,
        "ambiente": coletar_ambiente(),
        "resultados": tempos_por_config,
    }


def salvar_json(dados: dict, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=True, indent=2), encoding="utf-8")


def salvar_csv(dados: dict, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)

    with destino.open("w", newline="", encoding="utf-8") as arquivo_csv:
        writer = csv.writer(arquivo_csv)
        writer.writerow(
            [
                "processos",
                "media_tempo",
                "desvio_padrao",
                "speedup",
                "eficiencia",
            ]
        )

        for item in dados["resultados"]:
            writer.writerow(
                [
                    item["processos"],
                    f"{item['media_tempo']:.6f}",
                    f"{item['desvio_padrao']:.6f}",
                    f"{item['speedup']:.6f}",
                    f"{item['eficiencia']:.6f}",
                ]
            )


def gerar_graficos(dados: dict, pasta_graficos: Path) -> None:
    pasta_graficos.mkdir(parents=True, exist_ok=True)
    cores = paleta_graficos()

    processos = [item["processos"] for item in dados["resultados"]]
    tempos = [item["media_tempo"] for item in dados["resultados"]]
    speedups = [item["speedup"] for item in dados["resultados"]]
    eficiencias = [item["eficiencia"] for item in dados["resultados"]]

    gerar_grafico_linhas(
        caminho_saida=pasta_graficos / "tempo_execucao.png",
        x_valores=processos,
        y_series=[{"valores": tempos, "cor": cores["tempo"]}],
        y_maximo=max(tempos) * 1.1,
    )

    gerar_grafico_linhas(
        caminho_saida=pasta_graficos / "speedup.png",
        x_valores=processos,
        y_series=[
            {"valores": speedups, "cor": cores["speedup"]},
            {"valores": processos, "cor": cores["ideal"], "tracejado": True},
        ],
        y_maximo=max(max(speedups), max(processos)) * 1.1,
    )

    gerar_grafico_linhas(
        caminho_saida=pasta_graficos / "eficiencia.png",
        x_valores=processos,
        y_series=[{"valores": eficiencias, "cor": cores["eficiencia"]}],
        y_maximo=1.05,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa o benchmark da versao serial/paralela do analisador."
    )
    parser.add_argument(
        "--pasta",
        type=Path,
        default=LOG2_PADRAO,
        help="Pasta com os logs usados no experimento.",
    )
    parser.add_argument(
        "--repeticoes",
        type=int,
        default=3,
        help="Quantidade de execucoes por configuracao.",
    )
    parser.add_argument(
        "--processos",
        nargs="+",
        type=int,
        default=[2, 4, 8, 12],
        help="Configuracoes paralelas a testar.",
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
        default=BASE_DIR / "resultados" / "benchmark_log2.json",
        help="Arquivo JSON com os resultados.",
    )
    parser.add_argument(
        "--saida-csv",
        type=Path,
        default=BASE_DIR / "resultados" / "benchmark_log2.csv",
        help="Arquivo CSV com o resumo dos resultados.",
    )
    parser.add_argument(
        "--graficos",
        type=Path,
        default=BASE_DIR / "graficos",
        help="Pasta onde os graficos serao gerados.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dados = executar_benchmark(
        pasta=args.pasta,
        repeticoes=args.repeticoes,
        processos=args.processos,
        buffer_size=args.buffer,
    )

    salvar_json(dados, args.saida_json)
    salvar_csv(dados, args.saida_csv)
    gerar_graficos(dados, args.graficos)

    print(f"\nResultados salvos em: {args.saida_json}")
    print(f"Resumo CSV salvo em: {args.saida_csv}")
    print(f"Graficos salvos em: {args.graficos}")


if __name__ == "__main__":
    main()
