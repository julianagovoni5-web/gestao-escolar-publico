"""
cadastros/views.py

Views (API e Template): traduzem HTTP <-> Service. Não contêm regra de negócio.
"""
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.http import JsonResponse
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.views.generic import ListView, DetailView, View, CreateView, UpdateView, DeleteView

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from django.db.models.functions import Lower #Acréscimo da função de busca na página detalhe.html

from .models import (
    Pessoa, Funcao, CategoriaFuncao, DadosDocente, FormacaoDocente,
    AtribuicaoFuncao, HistoricoVinculoFormal, ExperienciaProfissional,
    PendenciaCadastro, Disciplina, ConteudoProgramatico,
    SubModulo, SubModuloDisciplina, Modulo, ModuloSubModulo,
    OfertaModulo, Turma, Ata, AtaPessoa,
)
from .forms import (
    CadastrarPessoaForm, EditarPessoaForm, FormacaoDocenteModelForm,
    HistoricoVinculoFormalModelForm, EncerrarHistoricoVinculoFormalForm,
    ExperienciaProfissionalModelForm, PendenciaCadastroModelForm,
    EditarPendenciaCadastroForm, EditarRequisitoContratacaoForm,
    FormacaoDocenteFormSet, ExperienciaProfissionalFormSet,
    HistoricoVinculoFormalFormSet, PendenciaCadastroFormSet,
    DisciplinaModelForm, DisciplinaToggleAtivoForm,
    ConteudoProgramaticoModelForm, ConteudoProgramaticoToggleAtivoForm,
    SubModuloModelForm, SubModuloToggleAtivoForm, SubModuloDisciplinaModelForm,
    ModuloModelForm, ModuloToggleAtivoForm, ModuloSubModuloModelForm,
    OfertaModuloModelForm, EncerrarOfertaModuloForm, TurmaModelForm,
    AtaModelForm, AtaPessoaModelForm,
)
from .services import (
    BuscarEnderecoPorCepService,
    CadastrarPessoaComFuncaoService,
)
from .serializers import (
    BuscarCepInputSerializer, EnderecoOutputSerializer,
    CadastrarPessoaInputSerializer, CadastrarPessoaOutputSerializer,
    BuscarPessoaPorCpfInputSerializer, PessoaOutputSerializer,
)


class BuscarCepView(APIView):
    """
    SRP: única responsabilidade é traduzir HTTP <-> BuscarEnderecoPorCepService.
    """

    def get(self, request, cep):
        input_serializer = BuscarCepInputSerializer(data={"cep": cep})
        input_serializer.is_valid(raise_exception=True)

        try:
            endereco = BuscarEnderecoPorCepService().executar(cep)
        except ValueError as e:
            return Response({"erro": str(e)}, status=status.HTTP_404_NOT_FOUND)

        output_serializer = EnderecoOutputSerializer(endereco.__dict__)
        return Response(output_serializer.data, status=status.HTTP_200_OK)


class BuscarPessoaPorCpfView(APIView):
    """
    SRP: busca uma Pessoa por CPF, para pré-preencher o formulário de
    cadastro quando o CPF já existir — parte da funcionalidade de
    reaproveitamento/edição de dados (docs/27). Só leitura, nunca cria
    nem altera nada — a atualização de verdade só acontece se o formulário
    for submetido depois (via CadastrarPessoaComFuncaoService).
    """

    def get(self, request, cpf):
        input_serializer = BuscarPessoaPorCpfInputSerializer(data={"cpf": cpf})
        input_serializer.is_valid(raise_exception=True)

        pessoa = Pessoa.objects.filter(cpf=input_serializer.validated_data["cpf"]).first()
        if not pessoa:
            return Response({"encontrada": False}, status=status.HTTP_200_OK)

        output_serializer = PessoaOutputSerializer(pessoa)
        return Response({"encontrada": True, "pessoa": output_serializer.data}, status=status.HTTP_200_OK)


class CadastrarPessoaView(APIView):
    """
    SRP: única responsabilidade é traduzir HTTP <-> CadastrarPessoaComFuncaoService.

    Versão mínima via API: cadastra Pessoa + AtribuicaoFuncao, sem os campos
    repetíveis (Formação/Experiência/Histórico/Pendências) — esses só estão
    disponíveis pelo formulário HTML (NovoCadastroPessoaView) por enquanto.
    """

    def post(self, request):
        input_serializer = CadastrarPessoaInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        dados = input_serializer.validated_data

        dados_pessoa = {
            "nome_completo": dados["nome_completo"],
            "cpf": dados["cpf"],
            "data_nascimento": dados["data_nascimento"],
            "email": dados["email"],
            "telefone": dados["telefone"],
            "endereco_cep": dados["endereco_cep"],
            "endereco_logradouro": dados["endereco_logradouro"],
            "endereco_numero": dados["endereco_numero"],
            "endereco_complemento": dados.get("endereco_complemento", ""),
            "endereco_bairro": dados["endereco_bairro"],
            "endereco_cidade": dados["endereco_cidade"],
            "endereco_uf": dados["endereco_uf"],
        }

        funcao = get_object_or_404(Funcao, pk=dados["funcao_id"])

        dados_atribuicao = {
            "data_inicio": dados["data_inicio"],
            "situacao": dados["situacao"],
        }

        try:
            pessoa, atribuicao, dados_docente = CadastrarPessoaComFuncaoService().executar(
                dados_pessoa=dados_pessoa,
                funcao=funcao,
                dados_atribuicao=dados_atribuicao,
            )
        except ValidationError as e:
            return Response({"erro": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        output_serializer = CadastrarPessoaOutputSerializer({
            "pessoa_id": pessoa.id,
            "nome_completo": pessoa.nome_completo,
            "funcao": funcao.nome,
            "atribuicao_id": atribuicao.id,
        })
        return Response(output_serializer.data, status=status.HTTP_201_CREATED)


class ListaPessoasView(ListView): #Acréscimo da função de busca na página detalhe.html
    """
    Lista de pessoas com:
    - busca por nome;
    - filtro por ativo/inativo;
    - filtro por categoria da função;
    - ordenação alfabética por nome.
    """

    model = Pessoa
    template_name = 'cadastros/lista.html'
    context_object_name = 'pessoas'

    def get_queryset(self):
        queryset = (
            Pessoa.objects
            .prefetch_related('atribuicoes__funcao')
            .order_by(Lower('nome_completo'))
        )

        # ------------------------------------------
        # FILTRO POR NOME
        # ------------------------------------------
        nome = self.request.GET.get('nome', '').strip()

        if nome:
            queryset = queryset.filter(
                nome_completo__icontains=nome
            )

        # ------------------------------------------
        # FILTRO ATIVO / INATIVO
        # ------------------------------------------
        ativo = self.request.GET.get('ativo', '')

        if ativo == '1':
            queryset = queryset.filter(ativo=True)

        elif ativo == '0':
            queryset = queryset.filter(ativo=False)

        # ------------------------------------------
        # FILTRO POR CATEGORIA
        # DISCENTE / DOCENTE / GESTAO
        # ------------------------------------------
        categoria = self.request.GET.get('categoria', '')

        categorias_validas = {
            CategoriaFuncao.DISCENTE,
            CategoriaFuncao.DOCENTE,
            CategoriaFuncao.GESTAO,
        }

        if categoria in categorias_validas:
            queryset = queryset.filter(
                atribuicoes__funcao__categoria=categoria
            ).distinct()

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Mantém os valores selecionados depois da pesquisa.
        context['filtro_nome'] = self.request.GET.get('nome', '')
        context['filtro_ativo'] = self.request.GET.get('ativo', '')
        context['filtro_categoria'] = self.request.GET.get('categoria', '')

        context['categorias_funcao'] = CategoriaFuncao.choices

        return context


class DetalhePessoaView(DetailView):
    """
    Template View: mostra os dados completos de uma Pessoa e seu Sumário
    Histórico de Vínculos. Único "centro de comando" da Pessoa desde a
    Etapa B (02/09/2026).

    "Funções" foi renomeado para "Sumário Histórico de Vínculos" em
    07/09/2026 (docs/37, seção 6) — não é uma tabela nova, é uma consulta
    consolidada: Docente/Gestão mostram 1-2 linhas direto de
    AtribuicaoFuncao; Discente mostra 1 linha por MatriculaTurma (lida via
    'atribuicao_funcao.matriculas_turma', o related_name do módulo
    atribuicao — leitura pura, sem nenhum import de lá, respeitando a
    fronteira entre os dois apps).
    """
    model = Pessoa
    template_name = 'cadastros/detalhe.html'
    context_object_name = 'pessoa'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sumario_historico_vinculos'] = self._construir_sumario_historico_vinculos()
        return context

    def _construir_sumario_historico_vinculos(self):
        linhas = []
        for atribuicao in self.object.atribuicoes.select_related('funcao').order_by('data_inicio'):
            if hasattr(atribuicao, 'dados_discente'):
                linhas.extend(self._linhas_discente(atribuicao))
            else:
                linhas.extend(self._linhas_docente_gestao(atribuicao))
        return linhas

    def _linhas_discente(self, atribuicao):
        """
        Reescrito em 08/09/2026 após teste manual real (docs/39): a versão
        anterior colapsava cada MatriculaTurma numa linha só (só o status
        final), perdendo o evento de entrada. Agora cada MatriculaTurma
        resolvida vira ATÉ 2 eventos — entrada (sempre, se data_inicio
        existir) e saída (só se status != CURSANDO) — cada um com sua
        própria data/Ata, ordenados cronologicamente.
        """
        canac = atribuicao.dados_discente.codigo_matricula_anac
        rotulo_funcao = f"{atribuicao.funcao.nome} (ANAC: {canac})" if canac else atribuicao.funcao.nome

        matriculas = list(
            atribuicao.matriculas_turma.select_related(
                'turma__oferta_modulo__modulo', 'ata_inicio', 'ata_encerramento'
            ).order_by('id')
        )

        linha_aguardando = {
            'funcao': rotulo_funcao,
            'situacao': atribuicao.get_situacao_display(),
            'ata': None,
            'data': atribuicao.data_inicio,
            'turma': None,
            'status_turma': 'Aguardando Atribuição',
            'evento': 'Aguardando Atribuição',
        }

        eventos = []
        for matricula in matriculas:
            if matricula.data_inicio:
                eventos.append({
                    'ata': str(matricula.ata_inicio) if matricula.ata_inicio else None,
                    'data': matricula.data_inicio,
                    'turma': matricula.turma.nome,
                    'status_turma': 'Cursando',
                    'evento': 'Relocação - entrada' if matricula.criada_por_relocacao else 'Início na turma',
                })
            # Comparação por string literal, não por enum — importar StatusMatriculaTurma
            # de atribuicao.models violaria a fronteira entre os apps (cadastros nunca
            # depende de atribuicao). 'CURSANDO'/'RELOCADO'/'APROVADO' são os choices
            # de MatriculaTurma.status, ver atribuicao/models.py.
            if matricula.status != 'CURSANDO':
                if matricula.status == 'RELOCADO':
                    descricao_evento = 'Relocação - saída'
                elif matricula.status == 'APROVADO':
                    descricao_evento = 'Conclusão da turma'
                else:
                    descricao_evento = f'Encerramento - {matricula.get_status_display()}'
                eventos.append({
                    'ata': str(matricula.ata_encerramento) if matricula.ata_encerramento else None,
                    'data': matricula.data_fim,
                    'turma': matricula.turma.nome,
                    'status_turma': matricula.get_status_display(),
                    'evento': descricao_evento,
                })

        # Se ainda não existe NENHUM evento concreto para mostrar — seja porque
        # a AtribuicaoFuncao nunca teve MatriculaTurma, seja porque já tem uma
        # (Turma ainda PLANEJADA, sem data_inicio) mas nada aconteceu de fato
        # ainda — mostra "Aguardando Atribuição". Bug real de teste manual
        # corrigido em 08/09/2026 (docs/39): a versão anterior checava só "existe
        # MatriculaTurma?", fazendo essa linha sumir prematuramente assim que o
        # aluno era adicionado a uma Turma ainda em planejamento.
        if not eventos:
            return [linha_aguardando]

        eventos.sort(key=lambda e: e['data'] or atribuicao.data_inicio)

        linhas = []
        ultimo_indice = len(eventos) - 1
        for indice, evento in enumerate(eventos):
            eh_ultimo = (indice == ultimo_indice)
            linhas.append({
                'funcao': rotulo_funcao,
                'situacao': atribuicao.get_situacao_display() if eh_ultimo else 'Ativo',
                **evento,
            })
        return linhas

    def _linhas_docente_gestao(self, atribuicao):
        linhas = [{
            'funcao': atribuicao.funcao.nome,
            'situacao': 'Ativo' if atribuicao.data_fim else atribuicao.get_situacao_display(),
            'ata': None,
            'data': atribuicao.data_inicio,
            'turma': None,
            'status_turma': None,
            'evento': 'Início de vínculo',
        }]
        if atribuicao.data_fim:
            linhas.append({
                'funcao': atribuicao.funcao.nome,
                'situacao': atribuicao.get_situacao_display(),
                'ata': None,
                'data': atribuicao.data_fim,
                'turma': None,
                'status_turma': None,
                'evento': 'Encerramento de vínculo',
            })
        return linhas


# Campo usado para decidir se uma linha de Formset foi de fato preenchida
# (Formsets sempre entregam a linha `extra`, mesmo vazia — precisa filtrar).
_CAMPO_PREENCHIDO = {
    'formacao': 'curso',
    'experiencia': 'organizacao',
    'historico': 'vinculo_formal',
    'pendencia': 'tipo',
}


def _linhas_preenchidas(cleaned_data_list, campo_chave):
    """Descarta linhas de Formset deixadas em branco (extra=1 sempre entrega 1 linha)."""
    return [linha for linha in cleaned_data_list if linha.get(campo_chave)]


class NovoCadastroPessoaView(View):
    """
    Template View: formulario HTML de cadastro. Reusa o mesmo Service
    da API (CadastrarPessoaComFuncaoService) — mesma regra de negocio,
    caminho de entrada diferente.

    Busca por CPF (docs/27): o campo CPF, ao apertar Enter, consulta
    /api/cadastros/pessoa-por-cpf/<cpf>/ e pré-preenche os demais campos
    se a Pessoa já existir — ver static/cadastros/js/buscar-cpf.js. Isso é
    só front-end; o back-end sempre aceita o POST completo normalmente,
    e o Service decide se cria ou atualiza a Pessoa pelo CPF.
    """
    template_name = 'cadastros/form_pessoa.html'

    def _formsets(self, dados_post=None):
        return (
            FormacaoDocenteFormSet(dados_post, prefix='formacao'),
            ExperienciaProfissionalFormSet(dados_post, prefix='experiencia'),
            HistoricoVinculoFormalFormSet(dados_post, prefix='historico'),
            PendenciaCadastroFormSet(dados_post, prefix='pendencia'),
        )

    def _funcao_categorias(self):
        """Mapa {id_da_funcao: categoria}, usado pelo JS para saber qual bloco mostrar."""
        return {f.id: f.categoria for f in Funcao.objects.all()}

    def get(self, request):
        form = CadastrarPessoaForm()
        formacao_fs, experiencia_fs, historico_fs, pendencia_fs = self._formsets()
        return render(request, self.template_name, {
            'form': form,
            'formacao_formset': formacao_fs,
            'experiencia_formset': experiencia_fs,
            'historico_formset': historico_fs,
            'pendencia_formset': pendencia_fs,
            'funcao_categorias': self._funcao_categorias(),
        })

    def post(self, request):
        form = CadastrarPessoaForm(request.POST)
        formacao_fs, experiencia_fs, historico_fs, pendencia_fs = self._formsets(request.POST)

        formularios_validos = (
            form.is_valid() and formacao_fs.is_valid()
            and experiencia_fs.is_valid() and historico_fs.is_valid()
            and pendencia_fs.is_valid()
        )
        if not formularios_validos:
            return render(request, self.template_name, {
                'form': form,
                'formacao_formset': formacao_fs,
                'experiencia_formset': experiencia_fs,
                'historico_formset': historico_fs,
                'pendencia_formset': pendencia_fs,
                'funcao_categorias': self._funcao_categorias(),
            })

        dados = form.cleaned_data
        funcao = dados['funcao']

        dados_pessoa = {
            "nome_completo": dados["nome_completo"],
            "cpf": dados["cpf"],
            "data_nascimento": dados["data_nascimento"],
            "email": dados["email"],
            "telefone": dados["telefone"],
            "registro_matricula": dados.get("registro_matricula") or None,
            "registro_aluno": dados.get("registro_aluno") or None,
            "codigo_anac": dados.get("codigo_anac") or None,
            "sexo": dados.get("sexo", ""),
            "identidade": dados.get("identidade", ""),
            "data_emissao_identidade": dados.get("data_emissao_identidade"),
            "orgao_expedidor_identidade": dados.get("orgao_expedidor_identidade", ""),
            "naturalidade": dados.get("naturalidade", ""),
            "uf_naturalidade": dados.get("uf_naturalidade", ""),
            "nacionalidade": dados.get("nacionalidade", ""),
            "filiacao_1": dados.get("filiacao_1", ""),
            "filiacao_2": dados.get("filiacao_2", ""),
            "nivel_instrucao": dados.get("nivel_instrucao", ""),
            "estado_civil": dados.get("estado_civil", ""),
            "raca_cor": dados.get("raca_cor", ""),
            "titulo_eleitor": dados.get("titulo_eleitor", ""),
            "zona_eleitoral": dados.get("zona_eleitoral", ""),
            "secao_eleitoral": dados.get("secao_eleitoral", ""),
            "email_2": dados.get("email_2", ""),
            "telefone_2": dados.get("telefone_2", ""),
            "passaporte": dados.get("passaporte", ""),
            "autorizacao_permanencia": dados.get("autorizacao_permanencia", ""),
            "endereco_cep": dados["endereco_cep"],
            "endereco_logradouro": dados["endereco_logradouro"],
            "endereco_numero": dados["endereco_numero"],
            "endereco_complemento": dados.get("endereco_complemento", ""),
            "endereco_bairro": dados["endereco_bairro"],
            "endereco_cidade": dados["endereco_cidade"],
            "endereco_uf": dados["endereco_uf"],
        }

        dados_atribuicao = {
            "data_inicio": dados["data_inicio"],
            "situacao": dados["situacao"],
        }

        # Requisitos de Contratação (RBAC 141) — todos exceto Discente.
        if funcao.categoria != CategoriaFuncao.DISCENTE:
            dados_atribuicao["requisito_contratacao"] = dados.get("requisito_contratacao", "")
            dados_atribuicao["documento_comprobatorio"] = dados.get("documento_comprobatorio", "")

        dados_extensao = None
        formacoes = None
        experiencias = None
        historico_vinculo_formal = None

        if funcao.categoria == CategoriaFuncao.DISCENTE:
            dados_extensao = {
                "codigo_matricula_anac": dados.get("codigo_matricula_anac") or None,
                "contato_emergencia_nome": dados.get("contato_emergencia_nome", ""),
                "contato_emergencia_parentesco": dados.get("contato_emergencia_parentesco", ""),
                "contato_emergencia_telefone": dados.get("contato_emergencia_telefone", ""),
                "contato_emergencia_endereco": dados.get("contato_emergencia_endereco", ""),
                "responsavel_nome": dados.get("responsavel_nome", ""),
                "responsavel_endereco": dados.get("responsavel_endereco", ""),
                "responsavel_identidade": dados.get("responsavel_identidade", ""),
                "responsavel_orgao_expedidor": dados.get("responsavel_orgao_expedidor", ""),
                "responsavel_data_emissao": dados.get("responsavel_data_emissao"),
                "responsavel_qualificacao": dados.get("responsavel_qualificacao", ""),
            }

        elif funcao.categoria == CategoriaFuncao.DOCENTE:
            dados_extensao = {}
            formacoes = _linhas_preenchidas(formacao_fs.cleaned_data, _CAMPO_PREENCHIDO['formacao'])
            historico_vinculo_formal = _linhas_preenchidas(
                historico_fs.cleaned_data, _CAMPO_PREENCHIDO['historico']
            )

        elif funcao.categoria == CategoriaFuncao.GESTAO:
            experiencias = _linhas_preenchidas(
                experiencia_fs.cleaned_data, _CAMPO_PREENCHIDO['experiencia']
            )
            historico_vinculo_formal = _linhas_preenchidas(
                historico_fs.cleaned_data, _CAMPO_PREENCHIDO['historico']
            )

        if funcao.categoria in (CategoriaFuncao.DOCENTE, CategoriaFuncao.GESTAO) and not historico_vinculo_formal:
            form.add_error(None, "É obrigatório informar ao menos um Histórico de Vínculo Formal para Docente ou Gestão.")
            return render(request, self.template_name, {
                'form': form,
                'formacao_formset': formacao_fs,
                'experiencia_formset': experiencia_fs,
                'historico_formset': historico_fs,
                'pendencia_formset': pendencia_fs,
                'funcao_categorias': self._funcao_categorias(),
            })

        # Universal — qualquer categoria
        pendencias = _linhas_preenchidas(pendencia_fs.cleaned_data, _CAMPO_PREENCHIDO['pendencia'])

        try:
            pessoa, atribuicao, dados_docente = CadastrarPessoaComFuncaoService().executar(
                dados_pessoa=dados_pessoa,
                funcao=funcao,
                dados_atribuicao=dados_atribuicao,
                dados_extensao=dados_extensao,
                formacoes=formacoes,
                experiencias=experiencias,
                historico_vinculo_formal=historico_vinculo_formal,
                pendencias=pendencias,
            )
        except ValidationError as e:
            form.add_error(None, e)
            return render(request, self.template_name, {
                'form': form,
                'formacao_formset': formacao_fs,
                'experiencia_formset': experiencia_fs,
                'historico_formset': historico_fs,
                'pendencia_formset': pendencia_fs,
                'funcao_categorias': self._funcao_categorias(),
            })

        return redirect('detalhe-pessoa', pk=pessoa.id)


class ModalCrudMixin:
    """
    Permite que a mesma View sirva tanto uma página completa (fallback sem
    JavaScript, acessando a URL direto) quanto um fragmento carregado via
    fetch() dentro de um popup/modal — o parâmetro ?parcial=1 na URL sinaliza
    o pedido do modal, retornando só o <form>, sem o layout do site em volta.
    No sucesso de um POST parcial, devolve JSON em vez de redirect, para o
    JavaScript do modal saber que deu certo (ver static/cadastros/js/
    modal-crud.js). Funciona tanto para CreateView/UpdateView (via form_valid)
    quanto para DeleteView (via delete) — mesmo mecanismo nos dois casos.
    """
    template_fragmento = None

    def eh_parcial(self):
        return self.request.GET.get('parcial') == '1'

    def get_template_names(self):
        if self.eh_parcial():
            assert self.template_fragmento, (
                f"{self.__class__.__name__} precisa definir template_fragmento"
            )
            return [self.template_fragmento]
        return [self.template_name]

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.eh_parcial():
            return JsonResponse({'sucesso': True})
        return response

    def delete(self, request, *args, **kwargs):
        response = super().delete(request, *args, **kwargs)
        if self.eh_parcial():
            return JsonResponse({'sucesso': True})
        return response


class EditarPessoaView(ModalCrudMixin, UpdateView):
    """Edita os campos comuns da Pessoa (identificação + endereço)."""
    model = Pessoa
    form_class = EditarPessoaForm
    template_name = 'cadastros/form_pessoa_editar.html'
    template_fragmento = 'cadastros/_form_pessoa_editar_fragment.html'

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.pk})


class AdicionarFormacaoDocenteView(ModalCrudMixin, CreateView):
    """Adiciona uma FormacaoDocente a um Docente já existente."""
    model = FormacaoDocente
    form_class = FormacaoDocenteModelForm
    template_name = 'cadastros/form_formacao.html'
    template_fragmento = 'cadastros/_form_formacao_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.dados_docente = get_object_or_404(DadosDocente, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.dados_docente = self.dados_docente
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['dados_docente'] = self.dados_docente
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.dados_docente.atribuicao.pessoa_id})


class EditarFormacaoDocenteView(ModalCrudMixin, UpdateView):
    """Edita um registro de Formação já existente."""
    model = FormacaoDocente
    form_class = FormacaoDocenteModelForm
    template_name = 'cadastros/form_formacao.html'
    template_fragmento = 'cadastros/_form_formacao_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['dados_docente'] = self.object.dados_docente
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.dados_docente.atribuicao.pessoa_id})


class ExcluirFormacaoDocenteView(ModalCrudMixin, DeleteView):
    """Exclusão real de FormacaoDocente."""
    model = FormacaoDocente
    template_name = 'cadastros/confirmar_exclusao.html'
    template_fragmento = 'cadastros/_confirmar_exclusao_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_voltar'] = reverse('detalhe-pessoa', kwargs={'pk': self.object.dados_docente.atribuicao.pessoa_id})
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.dados_docente.atribuicao.pessoa_id})


class AdicionarHistoricoVinculoFormalView(ModalCrudMixin, CreateView):
    """Adiciona um NOVO período de Vínculo Formal a uma AtribuicaoFuncao já existente."""
    model = HistoricoVinculoFormal
    form_class = HistoricoVinculoFormalModelForm
    template_name = 'cadastros/form_historico_vinculo.html'
    template_fragmento = 'cadastros/_form_historico_vinculo_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.atribuicao = get_object_or_404(AtribuicaoFuncao, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.atribuicao = self.atribuicao
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['atribuicao'] = self.atribuicao
        context['encerrando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.atribuicao.pessoa_id})


class EncerrarHistoricoVinculoFormalView(ModalCrudMixin, UpdateView):
    """Encerra um período de Vínculo Formal já existente — nunca Delete."""
    model = HistoricoVinculoFormal
    form_class = EncerrarHistoricoVinculoFormalForm
    template_name = 'cadastros/form_historico_vinculo.html'
    template_fragmento = 'cadastros/_form_historico_vinculo_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['atribuicao'] = self.object.atribuicao
        context['encerrando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.atribuicao.pessoa_id})


class AdicionarExperienciaProfissionalView(ModalCrudMixin, CreateView):
    """CRUD independente de ExperienciaProfissional (Gestão)."""
    model = ExperienciaProfissional
    form_class = ExperienciaProfissionalModelForm
    template_name = 'cadastros/form_experiencia.html'
    template_fragmento = 'cadastros/_form_experiencia_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.atribuicao = get_object_or_404(AtribuicaoFuncao, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.atribuicao = self.atribuicao
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['atribuicao'] = self.atribuicao
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.atribuicao.pessoa_id})


class EditarExperienciaProfissionalView(ModalCrudMixin, UpdateView):
    """Edita uma ExperienciaProfissional já existente."""
    model = ExperienciaProfissional
    form_class = ExperienciaProfissionalModelForm
    template_name = 'cadastros/form_experiencia.html'
    template_fragmento = 'cadastros/_form_experiencia_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['atribuicao'] = self.object.atribuicao
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.atribuicao.pessoa_id})


class ExcluirExperienciaProfissionalView(ModalCrudMixin, DeleteView):
    """Exclusão real de ExperienciaProfissional."""
    model = ExperienciaProfissional
    template_name = 'cadastros/confirmar_exclusao.html'
    template_fragmento = 'cadastros/_confirmar_exclusao_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_voltar'] = reverse('detalhe-pessoa', kwargs={'pk': self.object.atribuicao.pessoa_id})
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.atribuicao.pessoa_id})


class AdicionarPendenciaCadastroView(ModalCrudMixin, CreateView):
    """CRUD independente de PendenciaCadastro — universal, qualquer categoria."""
    model = PendenciaCadastro
    form_class = PendenciaCadastroModelForm
    template_name = 'cadastros/form_pendencia.html'
    template_fragmento = 'cadastros/_form_pendencia_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.atribuicao = get_object_or_404(AtribuicaoFuncao, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.atribuicao = self.atribuicao
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['atribuicao'] = self.atribuicao
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.atribuicao.pessoa_id})


class EditarPendenciaCadastroView(ModalCrudMixin, UpdateView):
    """Edita uma PendenciaCadastro já existente, incluindo marcar como resolvida."""
    model = PendenciaCadastro
    form_class = EditarPendenciaCadastroForm
    template_name = 'cadastros/form_pendencia.html'
    template_fragmento = 'cadastros/_form_pendencia_fragment.html'

    def form_valid(self, form):
        if form.instance.resolvida and not form.instance.resolvida_em:
            form.instance.resolvida_em = timezone.now()
        elif not form.instance.resolvida:
            form.instance.resolvida_em = None
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['atribuicao'] = self.object.atribuicao
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.atribuicao.pessoa_id})


class ExcluirPendenciaCadastroView(ModalCrudMixin, DeleteView):
    """Exclusão real de PendenciaCadastro."""
    model = PendenciaCadastro
    template_name = 'cadastros/confirmar_exclusao.html'
    template_fragmento = 'cadastros/_confirmar_exclusao_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_voltar'] = reverse('detalhe-pessoa', kwargs={'pk': self.object.atribuicao.pessoa_id})
        return context

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.atribuicao.pessoa_id})


class EditarRequisitoContratacaoView(ModalCrudMixin, UpdateView):
    """Edita os Requisitos de Contratação (RBAC 141) de uma AtribuicaoFuncao já existente."""
    model = AtribuicaoFuncao
    form_class = EditarRequisitoContratacaoForm
    template_name = 'cadastros/form_requisito_contratacao.html'
    template_fragmento = 'cadastros/_form_requisito_contratacao_fragment.html'

    def get_success_url(self):
        return reverse('detalhe-pessoa', kwargs={'pk': self.object.pessoa_id})


# --- Disciplina + ConteudoProgramatico (estrutura curricular, docs/33) ---
# CRU — sem Delete (nunca excluir Disciplina/ConteudoProgramatico de verdade,
# ver docs/33): o toggle de 'ativo' substitui a exclusão nos dois casos.

class ListaDisciplinasView(ListView):
    model = Disciplina
    template_name = 'cadastros/lista_disciplinas.html'
    context_object_name = 'disciplinas'
    ordering = ['nome']


class DetalheDisciplinaView(DetailView):
    model = Disciplina
    template_name = 'cadastros/detalhe_disciplina.html'
    context_object_name = 'disciplina'


class AdicionarDisciplinaView(ModalCrudMixin, CreateView):
    model = Disciplina
    form_class = DisciplinaModelForm
    template_name = 'cadastros/form_disciplina.html'
    template_fragmento = 'cadastros/_form_disciplina_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-disciplina', kwargs={'pk': self.object.pk})


class EditarDisciplinaView(ModalCrudMixin, UpdateView):
    model = Disciplina
    form_class = DisciplinaModelForm
    template_name = 'cadastros/form_disciplina.html'
    template_fragmento = 'cadastros/_form_disciplina_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-disciplina', kwargs={'pk': self.object.pk})


class ToggleAtivoDisciplinaView(ModalCrudMixin, UpdateView):
    """Confirmação simples + inverte Disciplina.ativo — substitui Excluir (CRU, sem Delete)."""
    model = Disciplina
    form_class = DisciplinaToggleAtivoForm
    template_name = 'cadastros/form_toggle_ativo_disciplina.html'
    template_fragmento = 'cadastros/_form_toggle_ativo_disciplina_fragment.html'

    def get_success_url(self):
        return reverse('detalhe-disciplina', kwargs={'pk': self.object.pk})


class AdicionarConteudoProgramaticoView(ModalCrudMixin, CreateView):
    model = ConteudoProgramatico
    form_class = ConteudoProgramaticoModelForm
    template_name = 'cadastros/form_conteudo_programatico.html'
    template_fragmento = 'cadastros/_form_conteudo_programatico_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.disciplina = get_object_or_404(Disciplina, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Disponibiliza a disciplina para validar o KP antes de salvar.
        form.instance.disciplina = self.disciplina
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['disciplina'] = self.disciplina
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-disciplina', kwargs={'pk': self.disciplina.pk})


class EditarConteudoProgramaticoView(ModalCrudMixin, UpdateView):
    model = ConteudoProgramatico
    form_class = ConteudoProgramaticoModelForm
    template_name = 'cadastros/form_conteudo_programatico.html'
    template_fragmento = 'cadastros/_form_conteudo_programatico_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['disciplina'] = self.object.disciplina
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-disciplina', kwargs={'pk': self.object.disciplina_id})


class ToggleAtivoConteudoProgramaticoView(ModalCrudMixin, UpdateView):
    """Confirmação simples + inverte ConteudoProgramatico.ativo — substitui Excluir."""
    model = ConteudoProgramatico
    form_class = ConteudoProgramaticoToggleAtivoForm
    template_name = 'cadastros/form_toggle_ativo_conteudo_programatico.html'
    template_fragmento = 'cadastros/_form_toggle_ativo_conteudo_programatico_fragment.html'

    def get_success_url(self):
        return reverse('detalhe-disciplina', kwargs={'pk': self.object.disciplina_id})


# --- SubModulo + SubModuloDisciplina (estrutura curricular, docs/33/docs/34) ---
# SubModulo é CRU (sem Delete, mesmo padrão de Disciplina). O vínculo com
# Disciplina (SubModuloDisciplina) permite Delete real — desvincular não afeta
# rastreabilidade, ConteudoProgramatico.disciplina aponta direto para
# Disciplina, nunca passa por este vínculo (ver docs/34).

class ListaSubModulosView(ListView):
    model = SubModulo
    template_name = 'cadastros/lista_submodulos.html'
    context_object_name = 'submodulos'
    ordering = ['nome']


class DetalheSubModuloView(DetailView):
    model = SubModulo
    template_name = 'cadastros/detalhe_submodulo.html'
    context_object_name = 'submodulo'


class AdicionarSubModuloView(ModalCrudMixin, CreateView):
    model = SubModulo
    form_class = SubModuloModelForm
    template_name = 'cadastros/form_submodulo.html'
    template_fragmento = 'cadastros/_form_submodulo_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-submodulo', kwargs={'pk': self.object.pk})


class EditarSubModuloView(ModalCrudMixin, UpdateView):
    model = SubModulo
    form_class = SubModuloModelForm
    template_name = 'cadastros/form_submodulo.html'
    template_fragmento = 'cadastros/_form_submodulo_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-submodulo', kwargs={'pk': self.object.pk})


class ToggleAtivoSubModuloView(ModalCrudMixin, UpdateView):
    """Confirmação simples + inverte SubModulo.ativo — substitui Excluir (CRU, sem Delete)."""
    model = SubModulo
    form_class = SubModuloToggleAtivoForm
    template_name = 'cadastros/form_toggle_ativo_submodulo.html'
    template_fragmento = 'cadastros/_form_toggle_ativo_submodulo_fragment.html'

    def get_success_url(self):
        return reverse('detalhe-submodulo', kwargs={'pk': self.object.pk})


class AdicionarSubModuloDisciplinaView(ModalCrudMixin, CreateView):
    """Vincula uma Disciplina já cadastrada a um SubModulo, com 'ordem'."""
    model = SubModuloDisciplina
    form_class = SubModuloDisciplinaModelForm
    template_name = 'cadastros/form_submodulo_disciplina.html'
    template_fragmento = 'cadastros/_form_submodulo_disciplina_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.submodulo = get_object_or_404(SubModulo, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['submodulo'] = self.submodulo
        return kwargs

    def form_valid(self, form):
        form.instance.submodulo = self.submodulo
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['submodulo'] = self.submodulo
        return context

    def get_success_url(self):
        return reverse('detalhe-submodulo', kwargs={'pk': self.submodulo.pk})


class ExcluirSubModuloDisciplinaView(ModalCrudMixin, DeleteView):
    """
    Desvincula uma Disciplina de um SubModulo — Delete real do VÍNCULO
    (SubModuloDisciplina), não da Disciplina em si. Reaproveita o template
    genérico de confirmação (mesmo usado por Formação/Experiência/Pendência).
    """
    model = SubModuloDisciplina
    template_name = 'cadastros/confirmar_exclusao.html'
    template_fragmento = 'cadastros/_confirmar_exclusao_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_voltar'] = reverse('detalhe-submodulo', kwargs={'pk': self.object.submodulo_id})
        return context

    def get_success_url(self):
        return reverse('detalhe-submodulo', kwargs={'pk': self.object.submodulo_id})


# --- Modulo + ModuloSubModulo (estrutura curricular, docs/33/docs/34) ---
# Mesmo padrão de SubModulo/SubModuloDisciplina, uma camada acima: Modulo é
# CRU (sem Delete); o vínculo com SubModulo permite Delete real (desvincular
# não afeta rastreabilidade, mesmo raciocínio de docs/34).

class ListaModulosView(ListView):
    model = Modulo
    template_name = 'cadastros/lista_modulos.html'
    context_object_name = 'modulos'
    ordering = ['nome']


class DetalheModuloView(DetailView):
    model = Modulo
    template_name = 'cadastros/detalhe_modulo.html'
    context_object_name = 'modulo'


class AdicionarModuloView(ModalCrudMixin, CreateView):
    model = Modulo
    form_class = ModuloModelForm
    template_name = 'cadastros/form_modulo.html'
    template_fragmento = 'cadastros/_form_modulo_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-modulo', kwargs={'pk': self.object.pk})


class EditarModuloView(ModalCrudMixin, UpdateView):
    model = Modulo
    form_class = ModuloModelForm
    template_name = 'cadastros/form_modulo.html'
    template_fragmento = 'cadastros/_form_modulo_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-modulo', kwargs={'pk': self.object.pk})


class ToggleAtivoModuloView(ModalCrudMixin, UpdateView):
    """Confirmação simples + inverte Modulo.ativo — substitui Excluir (CRU, sem Delete)."""
    model = Modulo
    form_class = ModuloToggleAtivoForm
    template_name = 'cadastros/form_toggle_ativo_modulo.html'
    template_fragmento = 'cadastros/_form_toggle_ativo_modulo_fragment.html'

    def get_success_url(self):
        return reverse('detalhe-modulo', kwargs={'pk': self.object.pk})


class AdicionarModuloSubModuloView(ModalCrudMixin, CreateView):
    """Vincula um SubModulo já cadastrado a um Modulo, com 'ordem'."""
    model = ModuloSubModulo
    form_class = ModuloSubModuloModelForm
    template_name = 'cadastros/form_modulo_submodulo.html'
    template_fragmento = 'cadastros/_form_modulo_submodulo_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.modulo = get_object_or_404(Modulo, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['modulo'] = self.modulo
        return kwargs

    def form_valid(self, form):
        form.instance.modulo = self.modulo
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['modulo'] = self.modulo
        return context

    def get_success_url(self):
        return reverse('detalhe-modulo', kwargs={'pk': self.modulo.pk})


class ExcluirModuloSubModuloView(ModalCrudMixin, DeleteView):
    """Desvincula um SubModulo de um Modulo — Delete real do VÍNCULO, não do SubModulo em si."""
    model = ModuloSubModulo
    template_name = 'cadastros/confirmar_exclusao.html'
    template_fragmento = 'cadastros/_confirmar_exclusao_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_voltar'] = reverse('detalhe-modulo', kwargs={'pk': self.object.modulo_id})
        return context

    def get_success_url(self):
        return reverse('detalhe-modulo', kwargs={'pk': self.object.modulo_id})


# --- OfertaModulo + Turma (estrutura curricular, docs/33/docs/35) ---
# OfertaModulo: lista independente (Módulo escolhido via dropdown, não pela URL).
# Só "Encerrar" na tela (exige data_fim) — Reativar é só pelo Django Admin, de
# propósito (decisão de 05/09/2026). Turma: CRU, nunca há Delete; 'situacao'
# muda via edição normal, sem botão dedicado (diferente do padrão Ativo/Inativo
# dos catálogos anteriores).

class ListaOfertaModulosView(ListView):
    model = OfertaModulo
    template_name = 'cadastros/lista_ofertas_modulo.html'
    context_object_name = 'ofertas'
    ordering = ['-ano_letivo', 'modulo__nome']


class DetalheOfertaModuloView(DetailView):
    model = OfertaModulo
    template_name = 'cadastros/detalhe_oferta_modulo.html'
    context_object_name = 'oferta'


class AdicionarOfertaModuloView(ModalCrudMixin, CreateView):
    model = OfertaModulo
    form_class = OfertaModuloModelForm
    template_name = 'cadastros/form_oferta_modulo.html'
    template_fragmento = 'cadastros/_form_oferta_modulo_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-oferta-modulo', kwargs={'pk': self.object.pk})


class EditarOfertaModuloView(ModalCrudMixin, UpdateView):
    model = OfertaModulo
    form_class = OfertaModuloModelForm
    template_name = 'cadastros/form_oferta_modulo.html'
    template_fragmento = 'cadastros/_form_oferta_modulo_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-oferta-modulo', kwargs={'pk': self.object.pk})


class EncerrarOfertaModuloView(ModalCrudMixin, UpdateView):
    """Só usada quando a Oferta está ativa — Reativar é exclusivo do Admin."""
    model = OfertaModulo
    form_class = EncerrarOfertaModuloForm
    template_name = 'cadastros/form_encerrar_oferta_modulo.html'
    template_fragmento = 'cadastros/_form_encerrar_oferta_modulo_fragment.html'

    def get_success_url(self):
        return reverse('detalhe-oferta-modulo', kwargs={'pk': self.object.pk})


class AdicionarTurmaView(ModalCrudMixin, CreateView):
    model = Turma
    form_class = TurmaModelForm
    template_name = 'cadastros/form_turma.html'
    template_fragmento = 'cadastros/_form_turma_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.oferta_modulo = get_object_or_404(OfertaModulo, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        # 'oferta_modulo' precisa estar na instância ANTES da validação rodar
        # (não só em form_valid, que roda depois) — senão a UniqueConstraint
        # (oferta_modulo, sigla) nunca é checada a tempo pelo Django, e uma
        # sigla duplicada só falha na hora de salvar, com IntegrityError cru
        # (tela de debug) em vez de mensagem amigável. Bug real de teste
        # manual, corrigido em 08/09/2026 (docs/39).
        kwargs = super().get_form_kwargs()
        if kwargs.get('instance') is None:
            kwargs['instance'] = Turma(oferta_modulo=self.oferta_modulo)
        return kwargs

    def form_valid(self, form):
        form.instance.oferta_modulo = self.oferta_modulo
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['oferta_modulo'] = self.oferta_modulo
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-oferta-modulo', kwargs={'pk': self.oferta_modulo.pk})


class EditarTurmaView(ModalCrudMixin, UpdateView):
    model = Turma
    form_class = TurmaModelForm
    template_name = 'cadastros/form_turma.html'
    template_fragmento = 'cadastros/_form_turma_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['oferta_modulo'] = self.object.oferta_modulo
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-oferta-modulo', kwargs={'pk': self.object.oferta_modulo_id})


class ListaTurmasView(ListView):
    """
    Lista global de Turmas, de todas as Ofertas de Modulo -- so leitura. Cada
    linha leva para o detalhe da Oferta correspondente (onde a Turma ja e
    editada via popup) -- decisao de 07/09/2026: nao existe detalhe_turma.html
    proprio, pois Turma nao tem nenhum "filho" (diferente de Modulo/Disciplina)
    e criaria uma segunda superficie de edicao sem necessidade real.
    """
    model = Turma
    template_name = 'cadastros/lista_turmas.html'
    context_object_name = 'turmas'

    def get_queryset(self):
        return Turma.objects.select_related('oferta_modulo', 'oferta_modulo__modulo').order_by(
            '-oferta_modulo__ano_letivo', 'oferta_modulo__modulo__nome', 'nome'
        )
        # Filtra automaticamente se o usuário vier pelo clique no card do Dashboard
        situacao = self.request.GET.get('situacao')
        if situacao:
            queryset = queryset.filter(situacao=situacao)
            
        return queryset


# --- Ata + AtaPessoa (estrutura curricular, docs/33; docs/35) ---
# Ata é CRU — Delete só pelo Django Admin (decisão de 05/09/2026). AtaPessoa é
# EXCEÇÃO PROVISÓRIA ao princípio "Pessoa amarrada = módulo Atribuição" (ver
# docstring de AtaPessoa em models.py) — destrava o uso real de Ata de
# Conselho/Orientação/Outro antes do módulo Atribuição existir; migra para lá
# quando ele for construído.

class ListaAtasView(ListView):
    model = Ata
    template_name = 'cadastros/lista_atas.html'
    context_object_name = 'atas'
    ordering = ['-data']


class DetalheAtaView(DetailView):
    model = Ata
    template_name = 'cadastros/detalhe_ata.html'
    context_object_name = 'ata'


class AdicionarAtaView(ModalCrudMixin, CreateView):
    model = Ata
    form_class = AtaModelForm
    template_name = 'cadastros/form_ata.html'
    template_fragmento = 'cadastros/_form_ata_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = False
        return context

    def get_success_url(self):
        return reverse('detalhe-ata', kwargs={'pk': self.object.pk})


class EditarAtaView(ModalCrudMixin, UpdateView):
    model = Ata
    form_class = AtaModelForm
    template_name = 'cadastros/form_ata.html'
    template_fragmento = 'cadastros/_form_ata_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('detalhe-ata', kwargs={'pk': self.object.pk})


class AdicionarAtaPessoaView(ModalCrudMixin, CreateView):
    """Vincula um Discente ativo a uma Ata — botão só aparece para finalidade Orientação/Conselho de Ensino/Outro (ver template)."""
    model = AtaPessoa
    form_class = AtaPessoaModelForm
    template_name = 'cadastros/form_ata_pessoa.html'
    template_fragmento = 'cadastros/_form_ata_pessoa_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.ata = get_object_or_404(Ata, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['ata'] = self.ata
        return kwargs

    def form_valid(self, form):
        form.instance.ata = self.ata
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['ata'] = self.ata
        return context

    def get_success_url(self):
        return reverse('detalhe-ata', kwargs={'pk': self.ata.pk})


class ExcluirAtaPessoaView(ModalCrudMixin, DeleteView):
    """Desvincula uma Pessoa de uma Ata — Delete real do VÍNCULO, não da Pessoa em si."""
    model = AtaPessoa
    template_name = 'cadastros/confirmar_exclusao.html'
    template_fragmento = 'cadastros/_confirmar_exclusao_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_voltar'] = reverse('detalhe-ata', kwargs={'pk': self.object.ata_id})
        return context

    def get_success_url(self):
        return reverse('detalhe-ata', kwargs={'pk': self.object.ata_id})

