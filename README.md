# Scripts_Revit

Extensao pyRevit com o plugin `Filters`.

## O que esta neste repositorio

Este repositorio ja inclui uma pasta pronta a copiar para o pyRevit:

```text
Scripts.extension/
  Scripts.tab/
    Ferramentas.panel/
      Filters.pushbutton/
```

O plugin permite:

- criar filtros a partir do projeto
- editar filtros existentes
- limpar filtros
- importar listas por `CSV` ou `Excel`
- transferir filtros por `JSON`
- guardar esquemas locais
- gerir uma paleta de cores

## Requisitos

- Autodesk Revit 2024 ou superior
- pyRevit instalado

Links uteis:

- pyRevit: https://www.pyrevitlabs.io/about
- GitHub do pyRevit: https://github.com/pyrevitlabs/pyRevit

## Instalacao

1. Instalar o pyRevit.
2. Fechar o Revit.
3. Abrir este repositorio no GitHub.
4. Clicar em `Code` -> `Download ZIP`.
5. Extrair o ZIP.
6. Copiar a pasta `Scripts.extension` extraida do ZIP para:

```text
%AppData%\pyRevit\Extensions
```

7. O resultado final deve ficar assim:

```text
%AppData%\pyRevit\Extensions\Scripts.extension\Scripts.tab\Ferramentas.panel\Filters.pushbutton
```

8. Abrir o Revit.
9. Fazer `Reload` no pyRevit, se necessario.

Depois disso, o botao deve aparecer em:

- tab `Scripts`
- panel `Ferramentas`
- botao `Filters`

## Instalacao por copia manual

Nao e preciso ter conta GitHub.

Tambem nao e preciso saber usar Git.

Basta:

1. abrir o repositorio no GitHub
2. clicar em `Code`
3. clicar em `Download ZIP`
4. extrair o ZIP
5. copiar a pasta `Scripts.extension` para `%AppData%\pyRevit\Extensions`

## Notas

- As paletas personalizadas e os esquemas sao guardados localmente no PC de cada utilizador.
- Este repositorio nao inclui paletas pessoais nem esquemas pessoais.
- O menu `Transferir filtros` serve para partilhar filtros entre colegas por ficheiro `JSON`.
- O menu `Esquemas` serve para reutilizacao local no mesmo PC.
