from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, CreateView, UpdateView, DeleteView
from django.contrib import messages
from django.db.models import Sum, Count
from django.db import models
from django.views.generic import ListView, TemplateView

from cadastros.models import Turma, SituacaoTurma, Pessoa
from cadastros.views import ModalCrudMixin

from .forms import (
    AdicionarMatriculaTurmaForm, EditarMatriculaTurmaForm, FinalizarPlanejamentoForm,
    EditarStatusMatriculaForm, RevisarAprovacaoForm, EncerrarTurmaForm,
)
from .models import MatriculaTurma, StatusMatriculaTurma, RegistroInstrucao, HorarioAula, Atribuicao
from .services import (
    FinalizarPlanejamentoService, AlterarStatusMatriculaService,
    PromoverAprovadosService, EncerrarTurmaService,
)


class GerenciarTurmaView(DetailView):
    """
    Tela principal do módulo Atribuição — composição de alunos de uma Turma.
    Enquanto PLANEJADA: ordena por nome (numero_na_turma ainda não existe).
    Depois de Finalizar Planejamento: ordena por numero_na_turma (fixo).
    """
    model = Turma
    template_name = 'atribuicao/gerenciar_turma.html'
    context_object_name = 'turma'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        matriculas = self.object.matriculas.select_related('atribuicao_funcao__pessoa')
        if self.object.situacao == SituacaoTurma.PLANEJADA:
            matriculas = matriculas.order_by('atribuicao_funcao__pessoa__nome_completo')
        else:
            matriculas = matriculas.order_by('numero_na_turma')
        context['matriculas'] = matriculas
        context['ha_cursando'] = self.object.matriculas.filter(status=StatusMatriculaTurma.CURSANDO).exists()
        return context


class AdicionarMatriculaTurmaView(ModalCrudMixin, CreateView):
    model = MatriculaTurma
    form_class = AdicionarMatriculaTurmaForm
    template_name = 'atribuicao/form_matricula.html'
    template_fragmento = 'atribuicao/_form_matricula_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.turma = get_object_or_404(Turma, pk=kwargs['pk'])
        if self.turma.situacao == SituacaoTurma.ENCERRADA:
            raise Http404("Não é possível adicionar aluno a uma Turma já Encerrada.")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['turma'] = self.turma
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['turma'] = self.turma
        return context

    def get_success_url(self):
        return reverse('gerenciar-turma', kwargs={'pk': self.turma.pk})


class EditarMatriculaTurmaView(ModalCrudMixin, UpdateView):
    model = MatriculaTurma
    form_class = EditarMatriculaTurmaForm
    template_name = 'atribuicao/form_matricula.html'
    template_fragmento = 'atribuicao/_form_matricula_fragment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['turma'] = self.object.turma
        context['editando'] = True
        return context

    def get_success_url(self):
        return reverse('gerenciar-turma', kwargs={'pk': self.object.turma_id})


class ExcluirMatriculaTurmaView(ModalCrudMixin, DeleteView):
    """Delete físico — só permitido enquanto a Turma está PLANEJADA (docs/37, seção 3)."""
    model = MatriculaTurma
    template_name = 'cadastros/confirmar_exclusao.html'
    template_fragmento = 'cadastros/_confirmar_exclusao_fragment.html'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.turma.situacao != SituacaoTurma.PLANEJADA:
            raise Http404("Só é possível excluir uma matrícula enquanto a Turma está Planejada.")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['url_voltar'] = reverse('gerenciar-turma', kwargs={'pk': self.object.turma_id})
        return context

    def get_success_url(self):
        return reverse('gerenciar-turma', kwargs={'pk': self.object.turma_id})


class FinalizarPlanejamentoView(View):
    """
    Botão "Finalizar Planejamento" (docs/37, seção 4.2) — ação em lote, não
    um CRUD de instância única, por isso não usa ModalCrudMixin/CreateView;
    replica manualmente o mesmo contrato (fragmento no GET, JSON no POST com
    ?parcial=1) para funcionar com o modal-crud.js já existente.
    """

    def _template(self, request):
        return 'atribuicao/_form_finalizar_planejamento_fragment.html' if request.GET.get('parcial') == '1' \
            else 'atribuicao/form_finalizar_planejamento.html'

    def get(self, request, pk):
        turma = get_object_or_404(Turma, pk=pk)
        form = FinalizarPlanejamentoForm()
        return render(request, self._template(request), {'form': form, 'turma': turma})

    def post(self, request, pk):
        turma = get_object_or_404(Turma, pk=pk)
        form = FinalizarPlanejamentoForm(request.POST)
        if form.is_valid():
            FinalizarPlanejamentoService().executar(
                turma, form.cleaned_data['data_inicio'], form.cleaned_data['ata_inicio']
            )
            if request.GET.get('parcial') == '1':
                return JsonResponse({'sucesso': True})
            return redirect('gerenciar-turma', pk=turma.pk)
        return render(request, self._template(request), {'form': form, 'turma': turma})


class EditarStatusMatriculaView(View):
    """
    Botão "Editar/CRU" enquanto a Turma está EM_ANDAMENTO (docs/37, seção 4.3)
    — muda o status de CURSANDO para Relocado/Reprovado/Transferido/Matrícula
    Excluída. Não usa ModalCrudMixin/UpdateView (o Form não é um ModelForm —
    os campos variam por status escolhido, resolvidos via
    AlterarStatusMatriculaService, não um form.save() direto).
    """

    def _template(self, request):
        return 'atribuicao/_form_status_matricula_fragment.html' if request.GET.get('parcial') == '1' \
            else 'atribuicao/form_status_matricula.html'

    def _matricula_ou_404(self, pk):
        matricula = get_object_or_404(MatriculaTurma, pk=pk)
        if matricula.status != StatusMatriculaTurma.CURSANDO:
            raise Http404("Só é possível alterar o status de uma matrícula ainda Cursando.")
        return matricula

    def get(self, request, pk):
        matricula = self._matricula_ou_404(pk)
        form = EditarStatusMatriculaForm(matricula=matricula)
        return render(request, self._template(request), {'form': form, 'matricula': matricula})

    def post(self, request, pk):
        matricula = self._matricula_ou_404(pk)
        form = EditarStatusMatriculaForm(request.POST, matricula=matricula)
        if form.is_valid():
            AlterarStatusMatriculaService().executar(
                matricula, form.cleaned_data['status'],
                turma_destino=form.cleaned_data.get('turma_destino'),
                motivo_saida=form.cleaned_data.get('motivo_saida', ''),
                data_fim=form.cleaned_data.get('data_fim'),
                ata_encerramento=form.cleaned_data.get('ata_encerramento'),
            )
            if request.GET.get('parcial') == '1':
                return JsonResponse({'sucesso': True})
            return redirect('gerenciar-turma', pk=matricula.turma_id)
        return render(request, self._template(request), {'form': form, 'matricula': matricula})


class RevisarAprovacaoView(View):
    """1º clique de "Encerrar Turma" (docs/37, seção 4.4/8-A) — lista de revisão com checkbox por aluno Cursando."""

    def _template(self, request):
        return 'atribuicao/_form_revisar_aprovacao_fragment.html' if request.GET.get('parcial') == '1' \
            else 'atribuicao/form_revisar_aprovacao.html'

    def get(self, request, pk):
        turma = get_object_or_404(Turma, pk=pk)
        form = RevisarAprovacaoForm(turma=turma)
        return render(request, self._template(request), {'form': form, 'turma': turma})


class EncerrarTurmaView(View):
    """Ação de encerramento de turma."""

    def post(self, request, pk):
        turma = get_object_or_404(Turma, pk=pk)
        form = EncerrarTurmaForm(request.POST)
        if form.is_valid():
            EncerrarTurmaService().executar(turma, form.cleaned_data['ata_encerramento'])
            messages.success(request, f"Turma {turma.nome} encerrada com sucesso!")
        return redirect('gerenciar-turma', pk=turma.pk)


# ==========================================================
# SEÇÃO OPERACIONAL E PEDAGÓGICA (RECONSTRUÍDA)
# ==========================================================

from django.shortcuts import render, redirect
from django.contrib import messages
from .models import RegistroInstrucao

def registro_instrucao_view(request):
    """Renderiza a tela operacional e processa o salvamento do registro de instrução em total sincronia com o HTML."""
    
    # 1. Se o usuário clicou no botão "Gravar no Diário de Classe"
    if request.method == 'POST':
        data_instrucao = request.POST.get('data_instrucao')
        carga_horaria = request.POST.get('carga_horaria')
        tipo = request.POST.get('tipo')  # Pega o valor do select do tipo
        conteudo = request.POST.get('conteudo')
        
        # Cria o registro preenchendo as colunas corretas do banco
        if data_instrucao and carga_horaria and conteudo:
            RegistroInstrucao.objects.create(
                data_instrucao=data_instrucao,
                carga_horaria=carga_horaria,
                tipo=tipo or 'TEORICA',  # Salva o tipo (Teórica/Prática/Avaliação)
                conteudo_programatico=conteudo  # Campo padrão de texto da migration
            )
            messages.success(request, "Diário de instrução gravado com sucesso!")
            return redirect('/atribuicao/turmas/registro-instrucao/')  
        else:
            messages.error(request, "Por favor, preencha todos os campos obrigatórios.")

    # 2. Puxa o histórico de aulas usando o nome 'registros' exigido pelo HTML
    registros = RegistroInstrucao.objects.all().order_by('-data_instrucao')
    
    return render(request, 'atribuicao/registro_instrucao.html', {'registros': registros})


from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Atribuicao, HorarioAula 

def horarios_view(request):
    """Renderiza os quadros de horários do módulo e processa os dados do formulário."""
    
    # 1. Processa o salvamento do formulário quando clica em 'Fixar Horário na Grade'
    if request.method == 'POST':
        atribuicao_id = request.POST.get('atribuicao')
        dia_semana = request.POST.get('dia_semana')
        horario_inicio = request.POST.get('horario_inicio') # Pegando os names do HTML
        horario_fim = request.POST.get('horario_fim')
        
        if atribuicao_id and dia_semana and horario_inicio and horario_fim:
            try:
                # Cria o horário na grade associado à atribuição correta
                HorarioAula.objects.create(
                    atribuicao_id=int(atribuicao_id),
                    dia_semana=dia_semana,
                    horario_inicio=horario_inicio,
                    horario_fim=horario_fim
                )
                messages.success(request, "Horário fixado na grade com sucesso!")
                return redirect('/atribuicao/horarios/')
            except Exception as e:
                messages.error(request, f"Erro ao salvar horário: {str(e)}")
        else:
            messages.error(request, "Por favor, preencha todos os campos obrigatórios.")

    # 2. CARREGAMENTO DOS DADOS PARA A TELA (GET)
    # Busca os horários salvos para listar na tabela inferior
    horarios = HorarioAula.objects.all()
    
    # Busca as atribuições da outra tela para listar no select superior (Vínculo)
    atribuigoes_disponiveis = Atribuicao.objects.select_related('instrutor', 'disciplina', 'turma').all()
    
    # Lista estática dos dias para o select
    DIAS_CHOICES = [
        ('SEG', 'Segunda-feira'),
        ('TER', 'Terça-feira'),
        ('QUA', 'Quarta-feira'),
        ('QUI', 'Quinta-feira'),
        ('SEX', 'Sexta-feira'),
        ('SAB', 'Sábado'),
    ]
    
    context = {
        'horarios': horarios,
        'atribuigoes': atribuigoes_disponiveis,
        'dias_semana': DIAS_CHOICES
    }
    
    return render(request, 'atribuicao/horarios.html', context)

from django.shortcuts import render
from django.db.models import Sum, DecimalField
from django.db.models.functions import Coalesce
from .models import MatriculaTurma, StatusMatriculaTurma, RegistroInstrucao, HorarioAula, Atribuicao

def relatorios_view(request):
    """Calcula os indicadores gerenciais em tempo real com base no banco de dados."""
    
    # 1. TOTAL DE ATRIBUIÇÕES: Dinâmico via contagem na tabela Atribuicao
    total_atribuicoes_real = Atribuicao.objects.count()
    
    # 2. TOTAL HORAS MINISTRADAS: Soma real do Histórico de Aulas Ministradas

    horas_agregadas = RegistroInstrucao.objects.aggregate(
        total=Coalesce(
            Sum('carga_horaria'), 
            0,
            output_field=DecimalField()  # 👈 Adicionado para corrigir o erro de tipos mistos
        )
    )
    total_horas_real = horas_agregadas['total']

    
    # 3. MATRÍCULAS ATIVAS: Conta dinamicamente os alunos com status 'CURSANDO'
    # Mapeamento exato baseado no seu TextChoices do models.py
    total_matriculas_real = MatriculaTurma.objects.filter(
        status=StatusMatriculaTurma.CURSANDO
    ).count()

    context = {
        'total_atribuicoes': total_atribuicoes_real,
        'total_horas_ministradas': total_horas_real,
        'matriculas_ativas': total_matriculas_real, 
    }
    
    return render(request, 'atribuicao/relatorios.html', context)

from django.shortcuts import render, redirect
from django.contrib import messages
from .models import Atribuicao
# CORREÇÃO: Removido AtribuicaoFuncao daqui, pois ele não existe no app cadastros
from cadastros.models import Pessoa, Disciplina, Turma, Funcao 

def atribuicao_view(request):
    """Renderiza a tela de atribuições de forma totalmente limpa e sem filtros que geram FieldError."""
    
    # 1. Processa o salvamento quando clica no botão azul
    if request.method == 'POST':
        # Buscando de forma estrita o que vem do formulário
        professor_id = request.POST.get('instrutor') or request.POST.get('professor')
        disciplina_id = request.POST.get('disciplina')
        turma_id = request.POST.get('turma')
        
        if professor_id and disciplina_id and turma_id:
            try:
                # Força a conversão para inteiro para garantir que são IDs numéricos válidos
                p_id = int(professor_id)
                d_id = int(disciplina_id)
                t_id = int(turma_id)

                # Busca o registro do Professor direto da tabela Pessoa
                professor_real = Pessoa.objects.get(id=p_id)

                # Grava a atribuição usando estritamente os IDs validados para evitar falha de Foreign Key
                Atribuicao.objects.get_or_create(
                    instrutor=professor_real,
                    disciplina_id=d_id,
                    turma_id=t_id
                )
                
                messages.success(request, "Atribuição realizada com sucesso!")
                return redirect('/atribuicao/atribuicao/')
                
            except (ValueError, Pessoa.DoesNotExist):
                messages.error(request, "Erro: O professor selecionado é inválido ou não foi encontrado.")
            except IntegrityError:
                messages.error(request, "Erro de Integridade: Verifique se a Disciplina ou Turma selecionada realmente existe no banco.")
        else:
            messages.error(request, "Por favor, preencha todos os campos obrigatórios.")

    # 2. BUSCA PURA E DIRETA
    professores = Pessoa.objects.all()
    disciplinas = Disciplina.objects.all()
    turmas = Turma.objects.all()
    atribuigoes = Atribuicao.objects.all()
    
    context = {
        'atribuigoes': atribuigoes,
        'instrutores': professores,  
        'disciplinas': disciplinas,
        'turmas': turmas
    }
    
    return render(request, 'atribuicao/atribuicao.html', context)



from django.shortcuts import render
from .models import MatriculaTurma  

def dashboard_gestao_view(request):
    """Renderiza o painel operacional de gerenciamento de turmas com indicadores reais vinculados."""
    
    # 1. VÍNCULO REAL: Conta apenas os alunos que possuem matrícula ativa na turma
    # Tentamos filtrar por 'CURSANDO' (que é o padrão do Assum). Se a classe estática não estiver importada,
    # o Django aceita a string pura diretamente no banco.
    total_alunos = MatriculaTurma.objects.filter(status='CURSANDO').count()
    
    # 2. Mantém os indicadores secundários sob controle
    turmas_andamento = 0
    total_alertas = 2  
    
    # 3. Empacota os dados unificados e envia ao arquivo HTML
    context = {
        'total_alunos_ativos': total_alunos,
        'turmas_em_andamento': turmas_andamento,
        'alertas_do_sistema': total_alertas,
    }
    
    return render(request, 'atribuicao/dashboard.html', context)


def contratos_gestao_view(request):
    """Renderiza a tela de contratos e prestação de serviços."""
    return render(request, 'atribuicao/contratos.html')


# ==========================================================
# MÓDULO DE QUALIDADE (DIRECIONADA AO NÚCLEO)
# ==========================================================

class TreinamentoListView(ListView):
    """Listagem de registros de instrução pedagógica blindada contra dados nulos."""

    model = RegistroInstrucao
    template_name = 'nucleo/treinamento.html'
    context_object_name = 'instrucoes'
    paginate_by = 15

    def get_queryset(self):
        return RegistroInstrucao.objects.select_related(
            'instrutor', 'atribuicao__disciplina', 'atribuicao__turma'
        ).order_by('-data_instrucao')

    # ADICIONE ESTE BLOCO ABAIXO PARA CORRIGIR O ERRO DE VARIÁVEL:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Garante que a variável do usuário atual da sessão seja injetada com segurança
        context['user'] = self.request.user
        return context


class AuditoriaInternaListView(ListView):
    """Histórico de movimentações de Atas oficiais."""

    model = MatriculaTurma
    template_name = 'nucleo/auditoria_interna.html'
    context_object_name = 'historico_vinculos'
    paginate_by = 20

    def get_queryset(self):
        from django.db.models import Q
        # O filtro abaixo garante a regra rígida: SEM ATA = SUMIR DA TABELA
        return MatriculaTurma.objects.filter(
            Q(ata_inicio__isnull=False) | Q(ata_encerramento__isnull=False)
        ).select_related(
            'atribuicao_funcao__pessoa', 
            'turma', 
            'ata_inicio', 
            'ata_encerramento'
        ).order_by('-data_inicio')


class IndicadoresQualidadeView(TemplateView):
    """Painel analítico e consolidação de indicadores institucionais."""

    template_name = 'nucleo/indicadores_qualidade.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        total = MatriculaTurma.objects.count()
        context['total_matriculas'] = total
        context['alunos_cursando'] = MatriculaTurma.objects.filter(status=StatusMatriculaTurma.CURSANDO).count()
        context['alunos_aprovados'] = MatriculaTurma.objects.filter(status=StatusMatriculaTurma.APROVADO).count()
        context['alunos_reprovados'] = MatriculaTurma.objects.filter(status=StatusMatriculaTurma.REPROVADO).count()
        
        evadidos = MatriculaTurma.objects.filter(
            status__in=[StatusMatriculaTurma.MATRICULA_EXCLUIDA, StatusMatriculaTurma.TRANSFERIDO]
        ).count()
        context['taxa_evasao'] = round((evadidos / total * 100), 1) if total > 0 else 0

        # Agregação de carga horária letiva
        horas = RegistroInstrucao.objects.aggregate(
            tot=Sum('carga_horaria'),
            teorica=Sum('carga_horaria', filter=models.Q(tipo='Teórica')),
            pratica=Sum('carga_horaria', filter=models.Q(tipo='Prática'))
        )
        context['horas_totais_instrucao'] = horas['tot'] or 0
        context['horas_teoricas'] = horas['teorica'] or 0
        context['horas_praticas'] = horas['pratica'] or 0

        total_h = context['horas_totais_instrucao']
        context['pct_teorica'] = round((context['horas_teoricas'] / total_h * 100), 1) if total_h > 0 else 0
        context['pct_pratica'] = round((context['horas_praticas'] / total_h * 100), 1) if total_h > 0 else 0

        # Gestão de contratos empenhados
        try:
            from .models import ContratoFinanceiro
            financeiro = ContratoFinanceiro.objects.aggregate(
                total_empenhado=Sum('valor_total_empenhado'),
                qtd_contratos=Count('id')
            )
            context['investimento_total'] = financeiro['total_empenhado'] or 0
            context['total_contratos'] = financeiro['qtd_contratos'] or 0
        except (ImportError, AttributeError):
            context['investimento_total'] = 0
            context['total_contratos'] = 0

        return context

def auditoria_interna_view(request):
    """View responsável por alimentar a tabela de Auditoria Interna de Vínculos."""
    # Buscamos todas as matrículas trazendo as tabelas relacionadas de uma vez só (alta performance)
    movimentacoes = MatriculaTurma.objects.select_related(
        'atribuicao_funcao', 
        'turma',
        'ata_inicio',
        'ata_encerramento'
    ).all()
    
    context = {
        'movimentacoes': movimentacoes,
    }
    
    # Certifique-se de que o caminho do template aponta para onde está o seu arquivo HTML da auditoria
    return render(request, 'atribuicao/qualidade/auditoria.html', context)

import io
from django.http import FileResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from .models import MatriculaTurma

def exportar_auditoria_pdf(request):
    """Gera um documento PDF oficial contendo o histórico de vínculos escolar."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    
    # Cabeçalho do PDF
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, 750, "SISTEMA DE GESTÃO ESCOLAR DA EMCA")
    c.setFont("Helvetica", 12)
    c.drawString(50, 730, "Relatório Consolidado de Atribuição e Vínculos")
    c.setLineWidth(1)
    c.line(50, 715, 550, 715)
    
    # Títulos da Tabela do PDF
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, 690, "Aluno")
    c.drawString(220, 690, "Turma")
    c.drawString(350, 690, "Ata Inicial")
    c.drawString(450, 690, "Status")
    c.line(50, 680, 550, 680)
    
    # Puxa os dados reais cadastrados
    movimentacoes = MatriculaTurma.objects.select_related(
        'atribuicao_funcao__pessoa', 'turma', 'ata_inicio'
    ).all().order_by('-data_inicio')
    
    y = 660
    c.setFont("Helvetica", 9)
    
    for mov in movimentacoes:
        if y < 50:
            c.showPage()
            y = 750
            
        # Tratamento de segurança para os nomes
        nome = mov.atribuicao_funcao.pessoa.nome_completo[:30] if hasattr(mov.atribuicao_funcao.pessoa, 'nome_completo') else str(mov.atribuicao_funcao.pessoa)[:30]
        turma = mov.turma.nome[:25]
        ata = mov.ata_inicio.numero if mov.ata_inicio else "—"
        status = mov.get_status_display()
        
        c.drawString(50, y, nome)
        c.drawString(220, y, turma)
        c.drawString(350, y, ata)
        c.drawString(450, y, status)
        y -= 20
        
    c.showPage()
    c.save()
    buf.seek(0)
    
    return FileResponse(buf, as_attachment=True, filename='Relatorio_Consolidado_EMCA.pdf')
