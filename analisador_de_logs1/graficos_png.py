from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

BRANCO = (255, 255, 255)
PRETO = (15, 23, 42)
CINZA = (203, 213, 225)
AZUL = (29, 78, 216)
VERDE = (15, 118, 110)
LARANJA = (180, 83, 9)
GRAFITE = (100, 116, 139)

FONTE_5X7 = {
    "0": ["111", "101", "101", "101", "101", "101", "111"],
    "1": ["010", "110", "010", "010", "010", "010", "111"],
    "2": ["111", "001", "001", "111", "100", "100", "111"],
    "3": ["111", "001", "001", "111", "001", "001", "111"],
    "4": ["101", "101", "101", "111", "001", "001", "001"],
    "5": ["111", "100", "100", "111", "001", "001", "111"],
    "6": ["111", "100", "100", "111", "101", "101", "111"],
    "7": ["111", "001", "001", "010", "010", "010", "010"],
    "8": ["111", "101", "101", "111", "101", "101", "111"],
    "9": ["111", "101", "101", "111", "001", "001", "111"],
    ".": ["0", "0", "0", "0", "0", "1", "1"],
    "-": ["0", "0", "0", "1", "0", "0", "0"],
}


class CanvasPNG:
    def __init__(self, largura: int, altura: int, fundo: tuple[int, int, int] = BRANCO) -> None:
        self.largura = largura
        self.altura = altura
        self._linhas = [
            bytearray([fundo[0], fundo[1], fundo[2]] * largura) for _ in range(altura)
        ]

    def set_pixel(self, x: int, y: int, cor: tuple[int, int, int]) -> None:
        if not (0 <= x < self.largura and 0 <= y < self.altura):
            return

        linha = self._linhas[y]
        indice = x * 3
        linha[indice] = cor[0]
        linha[indice + 1] = cor[1]
        linha[indice + 2] = cor[2]

    def draw_line(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        cor: tuple[int, int, int],
        espessura: int = 1,
        tracejado: bool = False,
    ) -> None:
        dx = x2 - x1
        dy = y2 - y1
        passos = max(abs(dx), abs(dy), 1)

        for passo in range(passos + 1):
            if tracejado and (passo // 8) % 2 == 1:
                continue

            x = round(x1 + (dx * passo / passos))
            y = round(y1 + (dy * passo / passos))

            raio = max(0, espessura // 2)
            for delta_x in range(-raio, raio + 1):
                for delta_y in range(-raio, raio + 1):
                    self.set_pixel(x + delta_x, y + delta_y, cor)

    def draw_circle(
        self,
        centro_x: int,
        centro_y: int,
        raio: int,
        cor: tuple[int, int, int],
    ) -> None:
        for y in range(centro_y - raio, centro_y + raio + 1):
            for x in range(centro_x - raio, centro_x + raio + 1):
                if (x - centro_x) ** 2 + (y - centro_y) ** 2 <= raio ** 2:
                    self.set_pixel(x, y, cor)

    def draw_text(
        self,
        x: int,
        y: int,
        texto: str,
        cor: tuple[int, int, int] = PRETO,
        escala: int = 2,
    ) -> None:
        cursor_x = x
        for caractere in texto:
            padrao = FONTE_5X7.get(caractere)
            if padrao is None:
                cursor_x += 4 * escala
                continue

            largura = len(padrao[0])
            for linha_idx, linha in enumerate(padrao):
                for coluna_idx, pixel in enumerate(linha):
                    if pixel != "1":
                        continue

                    for delta_x in range(escala):
                        for delta_y in range(escala):
                            self.set_pixel(
                                cursor_x + coluna_idx * escala + delta_x,
                                y + linha_idx * escala + delta_y,
                                cor,
                            )

            cursor_x += (largura + 1) * escala

    def save(self, caminho: Path) -> None:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        dados = b"".join(b"\x00" + bytes(linha) for linha in self._linhas)

        def chunk(tipo: bytes, conteudo: bytes) -> bytes:
            return (
                struct.pack(">I", len(conteudo))
                + tipo
                + conteudo
                + struct.pack(">I", zlib.crc32(tipo + conteudo) & 0xFFFFFFFF)
            )

        cabecalho = struct.pack(">IIBBBBB", self.largura, self.altura, 8, 2, 0, 0, 0)
        png = b"".join(
            [
                b"\x89PNG\r\n\x1a\n",
                chunk(b"IHDR", cabecalho),
                chunk(b"IDAT", zlib.compress(dados, level=9)),
                chunk(b"IEND", b""),
            ]
        )
        caminho.write_bytes(png)


def _mapear(valor: float, minimo: float, maximo: float, saida_min: int, saida_max: int) -> int:
    if math.isclose(maximo, minimo):
        return saida_min
    proporcao = (valor - minimo) / (maximo - minimo)
    return round(saida_min + proporcao * (saida_max - saida_min))


def _formatar_numero(valor: float) -> str:
    if valor >= 100:
        return f"{valor:.0f}"
    if valor >= 10:
        return f"{valor:.1f}"
    return f"{valor:.2f}"


def gerar_grafico_linhas(
    caminho_saida: Path,
    x_valores: list[int],
    y_series: list[dict],
    y_maximo: float,
    y_minimo: float = 0.0,
) -> None:
    largura = 900
    altura = 560
    margem_esquerda = 90
    margem_direita = 30
    margem_superior = 30
    margem_inferior = 70

    plot_x1 = margem_esquerda
    plot_y1 = margem_superior
    plot_x2 = largura - margem_direita
    plot_y2 = altura - margem_inferior
    largura_plot = plot_x2 - plot_x1
    altura_plot = plot_y2 - plot_y1

    canvas = CanvasPNG(largura, altura)

    for indice in range(6):
        valor = y_minimo + ((y_maximo - y_minimo) * indice / 5)
        y = _mapear(valor, y_minimo, y_maximo, plot_y2, plot_y1)
        canvas.draw_line(plot_x1, y, plot_x2, y, CINZA, espessura=1)

        texto = _formatar_numero(valor)
        deslocamento = len(texto) * 8
        canvas.draw_text(plot_x1 - deslocamento - 12, y - 8, texto, PRETO, escala=2)

    canvas.draw_line(plot_x1, plot_y1, plot_x1, plot_y2, PRETO, espessura=2)
    canvas.draw_line(plot_x1, plot_y2, plot_x2, plot_y2, PRETO, espessura=2)

    total_x = len(x_valores)
    divisor = max(1, total_x - 1)
    pontos_x = []
    for indice, valor in enumerate(x_valores):
        x = plot_x1 + round(largura_plot * indice / divisor)
        pontos_x.append(x)
        canvas.draw_line(x, plot_y2, x, plot_y2 + 6, PRETO, espessura=1)
        texto = str(valor)
        canvas.draw_text(x - (len(texto) * 4), plot_y2 + 14, texto, PRETO, escala=2)

    for serie in y_series:
        pontos = []
        for indice, valor in enumerate(serie["valores"]):
            y = _mapear(valor, y_minimo, y_maximo, plot_y2, plot_y1)
            pontos.append((pontos_x[indice], y))

        for (x1, y1), (x2, y2) in zip(pontos, pontos[1:]):
            canvas.draw_line(
                x1,
                y1,
                x2,
                y2,
                serie["cor"],
                espessura=3,
                tracejado=serie.get("tracejado", False),
            )

        for x, y in pontos:
            canvas.draw_circle(x, y, 4, serie["cor"])

    canvas.save(caminho_saida)


def paleta_graficos() -> dict:
    return {
        "tempo": VERDE,
        "speedup": AZUL,
        "ideal": GRAFITE,
        "eficiencia": LARANJA,
    }
