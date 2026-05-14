# Scripts_Revit

Extensao pyRevit com o plugin `Filters`.

## O que esta neste repositorio

Este repositorio ja inclui uma pasta pronta a copiar para o pyRevit:

```text
Scripts.extension/
  lib/
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

Basta:

1. abrir o repositorio no GitHub
2. clicar em `Code`
3. clicar em `Download ZIP`
4. extrair o ZIP
5. abrir a pasta extraida `Scripts_Revit-main`
6. copiar a pasta `Scripts.extension`
7. colar a pasta `Scripts.extension` em `%AppData%\pyRevit\Extensions`

Importante:

- copiar a pasta `Scripts.extension`
- nao copiar a pasta `Scripts_Revit-main`

Exemplo:

Depois de extrair o ZIP, vais ter algo deste genero:

```text
C:\Users\NOME\Downloads\Scripts_Revit-main
```

Dentro dessa pasta existe:

```text
C:\Users\NOME\Downloads\Scripts_Revit-main\Scripts.extension
```

E e essa pasta `Scripts.extension` que deve ser copiada para:

```text
C:\Users\NOME\AppData\Roaming\pyRevit\Extensions
```

## Notas

- As paletas personalizadas e os esquemas sao guardados localmente no PC de cada utilizador.
- Este repositorio nao inclui paletas pessoais nem esquemas pessoais.
- O menu `Transferir filtros` serve para partilhar filtros entre colegas por ficheiro `JSON`.
- O menu `Esquemas` serve para reutilizacao local no mesmo PC.
