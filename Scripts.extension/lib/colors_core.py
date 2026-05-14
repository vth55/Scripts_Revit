# -*- coding: utf-8 -*-
"""Geração de cores para filtros."""
import colorsys

PALETTE = [
    (220,  60,  60),  # vermelho
    ( 60, 160,  60),  # verde
    ( 60, 110, 210),  # azul
    (220, 140,   0),  # laranja
    (140,  40, 200),  # roxo
    (  0, 180, 180),  # ciano
    (200,  80, 160),  # rosa
    (100, 160,  50),  # verde lima
    ( 60, 120, 160),  # azul aço
    (210, 180,   0),  # amarelo
    (  0, 140, 120),  # verde petróleo
    (180,  90,  30),  # castanho
]


def hsv_gradient(n):
    """n cores distintas com saturation e value fixos."""
    result = []
    for i in range(n):
        r, g, b = colorsys.hsv_to_rgb(i / float(max(n, 1)), 0.72, 0.82)
        result.append((int(r * 255), int(g * 255), int(b * 255)))
    return result


def palette_cycle(n):
    """Cicla pela paleta fixa."""
    return [PALETTE[i % len(PALETTE)] for i in range(n)]


def get_colors(n, use_hsv=True):
    return hsv_gradient(n) if use_hsv else palette_cycle(n)
