# BI Aço Norte — Modelo Semântico Power BI

> Projeto Power BI no formato PBIP (moderno), versão **1.0 [dev]**  
> Compatibilidade: 1600 | Cultura: `pt-BR`

---

## Sumário

- [Visão Geral](#visão-geral)
- [Fontes de Dados](#fontes-de-dados)
- [Modelo de Dados](#modelo-de-dados)
  - [Tabelas Dimensão](#tabelas-dimensão)
  - [Tabelas Fato](#tabelas-fato)
  - [Tabelas Parâmetro](#tabelas-parâmetro)
  - [Relacionamentos](#relacionamentos)
- [Medidas DAX](#medidas-dax)
- [Análise de CMV](#análise-de-cmv)
- [Status das Medidas](#status-das-medidas)
- [Estrutura de Arquivos](#estrutura-de-arquivos)
- [Pendências e Próximos Passos](#pendências-e-próximos-passos)

---

## Visão Geral

Solução de Business Intelligence para a empresa **Aço Norte**, cobrindo os domínios de:

| Domínio | Descrição |
|---|---|
| Vendas | Faturamento, margem, ticket médio, metas |
| Estoque | Saldo, cobertura, situação de abastecimento |
| Movimentações | Entradas e saídas de produtos |
| Financeiro | Caixa, contas a pagar, contas a receber |
| CMV | Custo das Mercadorias Vendidas (preço de compra e venda) |
| Pedidos | Pedidos em aberto, cotações, recebimentos |
| Simulações | Estoque ideal, quantidade a comprar |

---

## Fontes de Dados

### Power Platform Dataflows

| Propriedade | Valor |
|---|---|
| WorkspaceId | `3302bffe-37e3-48cf-8e61-0e1eba5f63ce` |
| DataflowId | `0e903939-a26b-42c1-9cc2-baebc4f5b136` |

**Entidades carregadas via Dataflow:**

- `dim_pessoas`
- `dim_produtos`
- `dim_tipo_pg`
- `dim_contas_caixa`
- `fat_estoques`
- `fat_livro_caixa`
- `fat_movimento`
- `fat_vendas`
- `fat_vendas_cancel`
- `fat_caixa`

### SharePoint

| Propriedade | Valor |
|---|---|
| URL | `https://ypbi.sharepoint.com/sites/AcoNorte2` |
| Tabela | `Produtos Convert` (pedidos de compra) |
| ID da lista | `eeff6f52-9c2f-4d52-8216-e45a9b58bddc` |

### Dados Estáticos (embutidos no modelo)

- `dim_planos` — planos de venda (Table.FromRows)
- `Metas` — metas mensais de faturamento
- `dim_sistema` — gerado dinamicamente de `fat_vendas`
- `dim_vendedores` — gerado dinamicamente de `dim_pessoas`

---

## Modelo de Dados

### Tabelas Dimensão

| Tabela | Descrição | Chave |
|---|---|---|
| `dim_calendario` | Calendário completo com hierarquias de data | `Data` |
| `dim_pessoas` | Clientes e fornecedores | `id_pessoa` |
| `dim_produtos` | Cadastro de produtos com preços | `id_produto` |
| `dim_vendedores` | Vendedores (derivado de dim_pessoas) | `id_pessoa` |
| `dim_tipo_pg` | Tipos de pagamento | `codTipoPg` |
| `dim_planos` | Planos de venda | `idPlanoVenda` |
| `dim_contas_caixa` | Contas do caixa | `id_conta` |
| `dim_sistema` | Sistemas de origem dos dados | `ds_sistema` |
| `dim_status` | Status de pedidos (derivado de Produtos Convert) | `status` |
| `dim_ordem_venda` | Ordem de venda (derivado de Produtos Convert) | — |

### Tabelas Fato

| Tabela | Granularidade | Data principal |
|---|---|---|
| `fat_vendas` | Linha de venda por produto | `dt_venda` → `dim_calendario` |
| `fat_vendas_cancel` | Linha de venda cancelada | `dt_hr_venda_cancel` |
| `fat_estoques` | Snapshot de estoque por produto | `alterado` |
| `fat_movimento` | Movimento de entrada/saída | `dt_movimento` |
| `fat_caixa` | Lançamento financeiro | — |
| `fat_livro_caixa` | Lançamento do livro caixa | `dt_lancamento` |

**Convenção de `fat_movimento`:**

| Coluna | Valores | Significado |
|---|---|---|
| `tipo_movimento` | `"E"` / `"S"` | Entrada / Saída |
| `stMov` | `"E"` | Movimento efetivado |
| `finNFe` | `4` | NF-e de finalidade específica (excluir em entradas) |

### Tabelas Parâmetro

| Tabela | Tipo | Descrição |
|---|---|---|
| `par_meses_vendas` | GENERATESERIES(1,12) | Janela de meses para média de vendas |
| `par_meses_cobertura` | — | Meses de cobertura alvo |
| `par_meses_cobertura_simulada` | — | Meses de cobertura na simulação |
| `par_dias_sem_venda` | — | Limiar de dias sem venda |
| `par_dias_vendas` | — | Período em dias para média de vendas |
| `par_percent_margem` | — | Margem mínima aceitável |
| `par_qtd_estoque` | GENERATESERIES(0,10000) | Estoque mínimo para filtro |
| `par_atualizacao` | — | Data/hora da última atualização |
| `Parâmetro` | — | Seleção dinâmica geral |
| `Parâmetro vendas` | — | Seleção dinâmica de vendas |

### Relacionamentos

| De | Para | Cardinalidade | Direção |
|---|---|---|---|
| `fat_vendas.dt_venda` | `dim_calendario.Data` | N:1 | → |
| `fat_vendas.id_produto` | `dim_produtos.id_produto` | N:1 | → |
| `fat_vendas.id_cliente` | `dim_pessoas.id_pessoa` | N:1 | → |
| `fat_vendas.id_vendedor` | `dim_vendedores.id_pessoa` | N:1 | → |
| `fat_vendas.idPlanoVenda` | `dim_planos.idPlanoVenda` | N:1 | → |
| `fat_vendas.ds_sistema` | `dim_sistema.ds_sistema` | N:1 | → |
| `fat_movimento.id_produto` | `dim_produtos.id_produto` | N:1 | → |
| `fat_estoques.id_produto` | `dim_produtos.id_produto` | 1:N | ↔ bidirecional |
| `fat_caixa` | `dim_pessoas`, `dim_tipo_pg`, `dim_sistema` | N:1 | → |
| `Produtos Convert.id_produto` | `dim_produtos.id_produto` | N:1 | → |
| `Produtos Convert.status` | `dim_status.status` | N:1 | → |

> **Nota:** `fat_estoques.alterado` está vinculado a uma `LocalDateTable` privada, **não** ao `dim_calendario`. Filtros de data do relatório não se propagam ao fat_estoques.

---

## Medidas DAX

As medidas estão organizadas na tabela `Medidas` com as seguintes pastas:

### 1. Vendas

| Medida | Descrição |
|---|---|
| `qtd_transacoes` | Total de transações (DISTINCTCOUNT de cd_venda) |
| `qtd_vendas` | Quantidade total vendida |
| `qtd_vendedores` | Vendedores ativos no período |
| `vlr_vendas` | Receita bruta de vendas |
| `vlr_custo` | Custo total das vendas (qtd × vlr_custo) |
| `vlr_margem_bruta` | Receita − Custo |
| `%_margem_bruta` | Margem bruta percentual |
| `vlr_ticket_medio` | Receita / Transações |
| `vlr_desconto` | Total de descontos aplicados |
| `qtd_produtos` | Produtos distintos vendidos |
| `qtd_clientes` | Clientes distintos no período |
| `qtd_uni_produtos` | Contagem de linhas de produto |
| `%_margem_bruta_par` | Margem filtrada pelo parâmetro de margem mínima |
| `percentual_vendas` | % das vendas sobre o total selecionado |
| `dt_ultima_compra_cliente` | Data da última venda ao cliente |
| `Faturamento Ano Anterior` | Receita do mesmo período no ano anterior |
| `Faturamento Mês Anterior` | Receita do mês anterior |

### 2. Movimentações

| Medida | Descrição |
|---|---|
| `qtd_entradas` | Quantidade total de entradas efetivadas |
| `qtd_saidas` | Quantidade total de saídas efetivadas |
| `qtd_movimentos` | Total de movimentos (entradas + saídas) |
| `saldo_estoque` | Entradas − Saídas (baseado em movimentos) |
| `saldo_estoque_geral` | Saldo atual do snapshot (fat_estoques) |
| `saldo_estoque_all` | Saldo sem filtro de calendário |
| `vlr_estoque` | Valor do estoque atual a preço de compra |
| `vlr_estoque_vendas` | Valor do estoque atual a preço de venda |
| `valor_em_estoque` | Valor calculado via ADDCOLUMNS (preço venda × saldo) |
| `vlr_custo_unitario` | Custo unitário médio dos movimentos |
| `dt_primeira_entrada` | Data da primeira entrada do produto |
| `dt_ultima_saida` | Data da última saída do produto |
| `qtd_dias_sem_venda` | Dias desde a última saída |
| `qtd_vendas_3_meses` | Vendas nos últimos N meses (par_meses_vendas) |
| `qtd_venda_media_3_meses` | Média mensal de vendas no período |
| `qtd_vendas_dias` | Vendas nos últimos N dias (par_dias_vendas) |
| `qtd_venda_media` | Média diária de vendas extrapolada para 30 dias |
| `qtd_meses_capacidade_estoque` | Meses de estoque disponível (com pedidos em aberto) |
| `qtd_meses_capacidade_estoqueII` | Variação usando saldo a receber da tabela de pedidos |
| `situacao_abastecer_estoque` | Classificação: Comprar urgente / Aguardando / etc. |
| `qtd_meses_capacidade_estoque_2` | Indicador S/N se está abaixo do parâmetro de cobertura |
| `qtd_estoque_par` | Indicador S/N se atinge o estoque mínimo parametrizado |
| `qtd_produtos_estoque_negativo` | Produtos com saldo negativo |
| `qtd_produtos_estoque_zerado` | Produtos com saldo zero |
| `qtd_produtos_sem_venda_mais_30_dias` | Produtos sem venda de 31 a 60 dias |
| `qtd_produtos_sem_venda_mais_60_dias` | Produtos sem venda de 61 a 90 dias |
| `qtd_produtos_sem_venda_mais_90_dias` | Produtos sem venda há mais de 90 dias |
| `qtd_dias_sem_venda_par` | Indicador S/N baseado no parâmetro de dias sem venda |
| `max_entrada` | Data da última entrada do produto |
| `max_venda` | Data da última venda do produto |
| `vlr_peso` | Peso bruto total dos produtos |
| `estoque_adq` | Estoque atual + saldo a receber de pedidos |
| `Status_Estoque` | Classificação textual do status do estoque |

### 3. Financeiro

| Medida | Descrição |
|---|---|
| `vlr_caixa` | Total de lançamentos no caixa |
| `vlr_credito` | Lançamentos a crédito |
| `vlr_debito` | Lançamentos a débito |
| `vlr_saldo_caixa` | Crédito − Débito |
| `contas_a_pagar` | Débitos com status "A" (em aberto) |
| `contas_a_receber` | Créditos com status "A" (em aberto) |
| `vlr_meta` | Meta mensal de faturamento |
| `vlr_restante_meta` | Meta − Vendas realizadas |
| `vlr_venda_media_util` | Meta / Dias úteis do período |
| `vlr_venda_media_util_dia` | Meta diária com base nos dias úteis do mês |
| `vlr_restante_meta_dia` | Meta diária − Vendas do dia |
| `qtd_dias_uteis` | Dias úteis no período filtrado |
| `valor_total_estoque` | Preço máximo de venda × Saldo (por produto) |

### 4. CMV

> Calculado mensalmente pela fórmula: **EI + Compras − EF**
>
> O estoque inicial/final é reconstruído de forma reversa:
> `Estoque em DataFim = Estoque Atual − Entradas após DataFim + Saídas após DataFim`

| Medida | Descrição |
|---|---|
| `vlr_estoque_final_compra` | Estoque ao final do mês a preço de compra |
| `vlr_estoque_inicial_compra` | Estoque ao início do mês a preço de compra |
| `vlr_compras_mes` | Valor das entradas efetivadas no mês (vlr_total da NF) |
| `cmv_compra` | **CMV pela ótica do preço de compra** |
| `vlr_estoque_final_venda` | Estoque ao final do mês a preço de venda |
| `vlr_estoque_inicial_venda` | Estoque ao início do mês a preço de venda |
| `vlr_compras_mes_venda` | Entradas do mês valorizadas a preço de venda |
| `cmv_venda` | **CMV pela ótica do preço de venda** |

### 5. Preços

| Medida | Descrição |
|---|---|
| `max_preco_compra` | Maior preço de compra do produto |
| `max_preco_venda` | Maior preço de venda do produto |
| `media_preco_compra` | Preço de compra médio do produto |
| `media_preco_venda` | Preço de venda médio do produto |
| `%_margem_estoque` | Margem entre preço de venda e compra (máximos) |
| `%_margem_estoque_media` | Margem entre preço de venda e compra (médias) |
| `%_margem_par` | Indicador S/N se margem atinge o parâmetro |
| `vlr_custo_peso_compra` | Preço de compra por kg |
| `ultimo_preco` | Último preço de custo registrado em Produtos Convert |

### 6. Cotações *(inativas — aguardando fat_cotacoes)*

| Medida | Status |
|---|---|
| `vlr_cotacao` | ⛔ BLANK — fat_cotacoes não existe |
| `vlr_cotacao_anterior` | ⛔ BLANK — depende de vlr_cotacao |
| `%_variacao_cotacao` | ⛔ BLANK — depende de vlr_cotacao |
| `vlr_cotacao_max` | ⛔ BLANK — fat_cotacoes não existe |
| `vlr_cotacao_min` | ⛔ BLANK — fat_cotacoes não existe |

### 7. Pedidos

| Medida | Descrição |
|---|---|
| `qtd_pedidos_recebidos` | Quantidade recebida (status = "Recebido") |
| `qtd_pedidos_comprados` | Saldo a receber dos pedidos em aberto |
| `qtd_pedidos_comprados_nova_tabela` | Saldo a receber (coluna saldo_a_receber_cvt) |
| `qtd_pedidos_nova_tabela` | Quantidade total de pedidos |
| `qtd_pedidos_conf` | ⛔ BLANK — fat_pedidos_conf não existe |
| `qtd_dias_receber_pedido` | ⛔ BLANK — fat_pedidos não existe |
| `saldo_a_receber` | Soma de SaldoaReceber de Produtos Convert |

### 8. Simulações

| Medida | Descrição |
|---|---|
| `qtd_estoque_cobertura_simulada` | Quantidade ideal de estoque para N meses |
| `qtd_comprar_simulacao` | Qtd a comprar = cobertura − estoque adquirido |
| `qtd_comprar_simulacao2` | Variação: cobertura − saldo − pedidos em aberto |
| `vlr_peso_compra` | Quantidade a comprar em peso (ou unidade se sem peso) |
| `vlr_peso_compra_2` | Soma de vlr_peso_compra por produto (com VALUES) |
| `cobertura simulada` | Venda média × meses de cobertura simulada |

---

## Análise de CMV

### Metodologia

O CMV (Custo das Mercadorias Vendidas) é calculado pela fórmula contábil clássica:

```
CMV = Estoque Inicial + Compras − Estoque Final
```

### Por que reconstrução reversa?

`fat_estoques` é um **snapshot único** (não histórico) — todas as linhas têm a mesma data de atualização. A coluna `alterado` está vinculada a uma `LocalDateTable` privada, não ao `dim_calendario`, portanto filtros de período no relatório não atingem a tabela.

A solução foi **reconstruir o estoque histórico a partir do snapshot atual e dos movimentos**:

```
Estoque em DataFim = Estoque Atual
                   − Valor das entradas que ocorreram APÓS DataFim
                   + Valor das saídas que ocorreram APÓS DataFim
```

### Limitação conhecida

Os preços utilizados (`preco_compra`, `preco_venda`) são os **preços atuais** de `dim_produtos`, não preços históricos. Isso significa que em períodos mais antigos, se houve variação de preço, os valores do CMV terão distorção proporcional à variação.

---

## Status das Medidas

| Status | Quantidade | Descrição |
|---|---|---|
| ✅ Ativas | 93 | Funcionando corretamente |
| ⛔ Inativas | 5 | Aguardando tabelas `fat_cotacoes` e `fat_pedidos_conf` |

---

## Estrutura de Arquivos

```
bi_aconorte/
├── cd_aco_norte 1.0 [dev].pbip            # Arquivo de projeto PBIP
├── cd_aco_norte 1.0 [dev].SemanticModel/
│   ├── definition.pbism                   # Configuração do modelo
│   └── definition/
│       ├── model.tmdl                     # Configurações gerais
│       ├── relationships.tmdl             # Todos os relacionamentos
│       └── tables/
│           ├── Medidas.tmdl               # 98 medidas DAX
│           ├── dim_calendario.tmdl
│           ├── dim_produtos.tmdl
│           ├── dim_pessoas.tmdl
│           ├── fat_vendas.tmdl
│           ├── fat_estoques.tmdl
│           ├── fat_movimento.tmdl
│           ├── fat_caixa.tmdl
│           └── ...
└── cd_aco_norte 1.0 [dev].Report/
    └── definition/
        └── report.json                    # Layout e páginas do relatório
```

---

## Pendências e Próximos Passos

### Prioridade Alta

- [ ] Criar as tabelas `fat_cotacoes`, `fat_pedidos` e `fat_pedidos_conf` no Dataflow e reativar as 5 medidas inativas da pasta **6. Cotações** e **7. Pedidos**
- [ ] Converter `dim_status` e `dim_ordem_venda` em tabelas permanentes independentes (atualmente derivadas de `Produtos Convert` via SUMMARIZE)

### Prioridade Média

- [ ] Substituir as 24 `LocalDateTables` por relacionamentos diretos com `dim_calendario` onde aplicável
- [ ] Revisar o relacionamento bidirecional `fat_estoques ↔ dim_produtos` (pode causar ambiguidade em análises cross-filter)
- [ ] Adicionar descrições nas colunas principais para documentação interna do Power BI

### Prioridade Baixa

- [ ] Padronizar nomenclatura: remover acentos e espaços de nomes de tabelas (`Produtos Convert`, `Parâmetro`)
- [ ] Revisar `SELECTEDVALUE` sem valor padrão nas medidas de parâmetro (podem retornar BLANK quando nenhum valor está selecionado)

---

*Documentação gerada em 2026-04-20*
