"""
nucleo/menu.py

Fonte única do menu de navegação (sidebar), agrupado por ator, conforme
desenho trazido pela pessoa responsável em 06/09/2026 (slides 1-4 do modelo
de tela de navegação).

IMPORTANTE — isso NÃO é controle de acesso. É só a camada visual de links,
mostrada da mesma forma pra qualquer pessoa que acessar o sistema, porque
ainda não existe login/autenticação (previsto para o futuro, ver Backlog).
Quando o login existir, esta estrutura precisará ser filtrada por Funcao da
Pessoa autenticada — hoje ela é só decorativa/organizacional.

Cada item tem:
- 'label': texto mostrado na tela.
- 'url_name': uma URL de verdade (já implementada), ou None (módulo ainda não
  implementado — leva para a tela "Em Construção").
- 'url_names_ativos' (só quando url_name existe): lista de TODOS os `name=`
  de View que devem contar como "você está aqui" para este item.
- 'chave' (só quando url_name é None): identificador ÚNICO no sistema
  inteiro, usado na URL /em-construcao/<chave>/ — NUNCA repetir uma chave
  entre itens, mesmo que o 'label' seja igual (ex: "Relatórios" aparece em
  3 grupos, mas cada um tem sua própria chave: 'relatorios-gestao',
  'relatorios-secretaria', 'relatorios-coordenacao'). Corrige um bug real de
  07/09/2026: usar o 'label' como identificador fazia os 3 itens "Relatórios"
  acenderem juntos, por serem indistinguíveis para o sistema.

'Turma' tem lista própria (lista_turmas.html) mas SEM detalhe próprio —
'adicionar-turma'/'editar-turma' contam como o item Turma ativo.
"""

MENU_NAVEGACAO = [   {
        "grupo": "Gestão",
        "itens": [
            {"label": "Dashboard", "url_name": "dashboard", "chave": "dashboard"},
            {"label": "Contratos", "url_name": "contratos", "chave": "contratos"},
            {"label": "Relatórios", "url_name": "relatorios", "chave": "relatorios-gestao"},
        ],
    },
        {
        "grupo": "Qualidade",
        "itens": [
            {"label": "Treinamento", "url_name": "qualidade-treinamento", "chave": "treinamento"},
            {"label": "Auditoria Interna", "url_name": "qualidade-auditoria", "chave": "auditoria-interna"},
        ]
    },

    {
        "grupo": "Secretaria",
        "itens": [
            {
                "label": "Pessoa",
                "url_name": "lista-pessoas",
                "url_names_ativos": [
                    "lista-pessoas", "detalhe-pessoa", "novo-cadastro-pessoa", "editar-pessoa",
                    "adicionar-formacao-docente", "editar-formacao-docente", "excluir-formacao-docente",
                    "adicionar-historico-vinculo", "encerrar-historico-vinculo",
                    "adicionar-experiencia", "editar-experiencia", "excluir-experiencia",
                    "adicionar-pendencia", "editar-pendencia", "excluir-pendencia",
                    "editar-requisito-contratacao",
                ],
            },
            {
                "label": "Disciplinas",
                "url_name": "lista-disciplinas",
                "url_names_ativos": [
                    "lista-disciplinas", "detalhe-disciplina", "adicionar-disciplina",
                    "editar-disciplina", "toggle-ativo-disciplina",
                    "adicionar-conteudo-programatico", "editar-conteudo-programatico",
                    "toggle-ativo-conteudo-programatico",
                ],
            },
            {
                "label": "SubModulo",
                "url_name": "lista-submodulos",
                "url_names_ativos": [
                    "lista-submodulos", "detalhe-submodulo", "adicionar-submodulo",
                    "editar-submodulo", "toggle-ativo-submodulo",
                    "adicionar-submodulo-disciplina", "excluir-submodulo-disciplina",
                ],
            },
            {
                "label": "Modulo",
                "url_name": "lista-modulos",
                "url_names_ativos": [
                    "lista-modulos", "detalhe-modulo", "adicionar-modulo",
                    "editar-modulo", "toggle-ativo-modulo",
                    "adicionar-modulo-submodulo", "excluir-modulo-submodulo",
                ],
            },
            {
                "label": "Oferta de Modulo",
                "url_name": "lista-ofertas-modulo",
                "url_names_ativos": [
                    "lista-ofertas-modulo", "detalhe-oferta-modulo",
                    "adicionar-oferta-modulo", "editar-oferta-modulo", "encerrar-oferta-modulo",
                ],
            },
            {
                "label": "Turma",
                "url_name": "lista-turmas",
                "url_names_ativos": [
                    "lista-turmas", "adicionar-turma", "editar-turma",
                    "gerenciar-turma", "adicionar-matricula-turma", "editar-matricula-turma",
                    "excluir-matricula-turma", "editar-status-matricula",
                    "finalizar-planejamento", "revisar-aprovacao", "encerrar-turma",
                ],
            },
            {
                "label": "Ata",
                "url_name": "lista-atas",
                "url_names_ativos": [
                    "lista-atas", "detalhe-ata", "adicionar-ata", "editar-ata",
                    "adicionar-ata-pessoa", "excluir-ata-pessoa",
                ],
            },
            {"label": "Relatórios", "url_name": None, "chave": "relatorios-secretaria"},
        ],
    },
    {
        "grupo": "Coordenação",
        "itens": [
            {"label": "Atribuição", "url_name": "atribuicao", "chave": "atribuicao"},
            {"label": "Horários", "url_name": "horarios", "chave": "horarios"},
            {"label": "Relatórios", "url_name": "relatorios", "chave": "relatorios-coordenacao"},
        ],
    },
    {
        "grupo": "Instrutores",
        "itens": [
            {"label": "Registro de Instrução", "url_name": "registro_instrucao", "chave": "registro-instrucao"},
        ],
    },
]
