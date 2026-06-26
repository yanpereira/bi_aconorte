# Contexto Completo do Modelo de BI — Aço Norte

## A Empresa
Aço Norte é uma distribuidora de aços localizada no Ceará. Opera com vendas B2B para construtoras, indústrias e revendedores. O modelo de dados cobre quatro pilares: **Vendas, Estoque/Movimentações, Financeiro e Pedidos de Compra**.

---

## Estrutura do Modelo de Dados

### Tabelas Fato
| Tabela | O que contém |
|--------|-------------|
| `fat_vendas` | Cada item vendido: produto, cliente, vendedor, valor, custo, desconto, data |
| `fat_caixa` | Lançamentos financeiros: créditos (C) e débitos (D), status Aberto (A) ou Efetivado (E) |
| `fat_estoques` | Posição atual de estoque por produto: quantidade, preço de compra e preço de venda |
| `fat_movimento` | Entradas (E) e saídas (S) de estoque — base do controle de movimentação |
| `fat_livro_caixa` | Livro caixa detalhado com todos os lançamentos |
| `fat_vendas_cancel` | Vendas canceladas (separadas das vendas efetivadas) |
| `Produtos Convert` | Pedidos de compra em andamento: quantidade pedida, recebida, saldo a receber, custo unitário |

### Tabelas Dimensão
| Tabela | O que contém |
|--------|-------------|
| `dim_produtos` | Cadastro de produtos: código, descrição, preço de venda, preço de compra, saldo de estoque, peso bruto, data da última entrada, data da última venda, dias sem venda |
| `dim_pessoas` | Clientes e pessoas do sistema |
| `dim_vendedores` | Cadastro de vendedores |
| `dim_calendario` | Calendário com dias úteis, mês/ano (Anomes), últimos dias/meses |
| `dim_contas_caixa` | Contas a pagar e a receber com datas de lançamento, vencimento, baixa |
| `dim_planos` | Planos de venda (tabela de preços / condições) |
| `dim_tipo_pg` | Tipos de pagamento |
| `dim_sistema` | Sistemas de origem dos lançamentos |

---

## Medidas e Indicadores (definições em linguagem natural)

### 1. VENDAS
- **vlr_vendas**: Soma total do valor de venda (vlr_venda_total). É o faturamento bruto.
- **vlr_custo**: Custo total das mercadorias vendidas no período = qtd_vendida × vlr_custo_unitário.
- **vlr_margem_bruta**: Faturamento menos custo (vlr_vendas − vlr_custo). Margem em R$.
- **%_margem_bruta**: Margem bruta dividida pelo faturamento. Quanto o negócio ganha em % sobre o que vende.
- **vlr_ticket_medio**: Faturamento dividido pelo número de transações (NF/pedidos distintos).
- **qtd_transacoes**: Quantidade de notas fiscais/pedidos distintos (DISTINCTCOUNT de cd_venda).
- **qtd_vendas**: Volume em unidades vendidas.
- **qtd_clientes**: Clientes que compraram no período (DISTINCTCOUNT de cd_cliente).
- **qtd_vendedores**: Vendedores ativos no período (DISTINCTCOUNT de cd_vendedor).
- **qtd_produtos**: Produtos distintos vendidos no período.
- **vlr_desconto**: Valor total de descontos concedidos.
- **vlr_meta**: Meta de faturamento do mês (vem da tabela Metas, filtrada pelo mês/ano do calendário).
- **vlr_restante_meta**: O quanto falta para bater a meta = vlr_meta − vlr_vendas. Se negativo, a meta foi superada.
- **vlr_venda_media_util_dia**: Valor que precisa ser vendido por dia útil para atingir a meta = Meta ÷ Dias úteis do mês.
- **Faturamento Mês Anterior**: Faturamento do mês imediatamente anterior ao período selecionado.
- **Faturamento Ano Anterior**: Faturamento do mesmo período do ano anterior.

### 2. ESTOQUE E MOVIMENTAÇÕES
- **saldo_estoque_geral**: Posição atual de estoque em quantidade (sum da coluna `estoque` de fat_estoques).
- **vlr_estoque (compra)**: Valor do estoque positivo avaliado pelo preço de compra = Σ (qty × preço_compra) para itens com estoque > 0.
- **vlr_estoque_vendas (venda)**: Valor do estoque positivo avaliado pelo preço de venda = Σ (qty × preço_venda).
- **qtd_produtos_estoque_negativo**: Produtos com saldo de estoque abaixo de zero (inconsistência ou venda a descoberto).
- **qtd_produtos_estoque_zerado**: Produtos com saldo exatamente zero (sem estoque, possível ruptura).
- **qtd_produtos_sem_venda_mais_30_dias**: Produtos com última venda entre 30 e 60 dias atrás.
- **qtd_produtos_sem_venda_mais_60_dias**: Produtos com última venda entre 60 e 90 dias atrás.
- **qtd_produtos_sem_venda_mais_90_dias**: Produtos com última venda há mais de 90 dias (estoque parado/obsoleto).
- **qtd_dias_sem_venda**: Para cada produto, quantos dias desde a última saída.
- **qtd_venda_media**: Média de venda por mês calculada sobre os últimos N dias (parâmetro par_dias_vendas) × 30.
- **qtd_meses_capacidade_estoque**: Quantos meses o estoque atual aguenta com a média de vendas = (Estoque + Pedidos em aberto) ÷ Venda média mensal.
- **situacao_abastecer_estoque**: Classificação automática por produto:
  - *"Comprar urgentemente"*: menos de 2 meses de cobertura e sem pedido de compra aberto
  - *"Comprar quando possível"*: mais de 2 meses de cobertura e sem pedido de compra aberto
  - *"Aguardando recebimento"*: com pedido de compra em aberto
  - *"Verificar real situação"*: cobertura negativa (estoque negativo)
- **Status_Estoque**: Alerta simples — "Com estoque e sem venda" ou "Sem estoque e sem venda".
- **saldo_estoque_all**: Saldo de estoque geral ignorando filtros de data (sempre mostra a posição atual).
- **dt_ultima_saida / dt_ultima_entrada**: Datas da última movimentação de saída/entrada por produto.

### 3. FINANCEIRO
- **vlr_caixa**: Soma de todos os lançamentos do caixa.
- **vlr_credito**: Apenas lançamentos do tipo "C" (entradas de caixa, recebimentos).
- **vlr_debito**: Apenas lançamentos do tipo "D" (saídas de caixa, pagamentos).
- **vlr_saldo_caixa**: Créditos menos Débitos = posição líquida do caixa no período.
- **contas_a_pagar**: Débitos com status "A" (Aberto) — o que ainda vai ser pago.
- **contas_a_receber**: Créditos com status "A" (Aberto) — o que ainda vai ser recebido.
- **qtd_dias_uteis**: Dias úteis no período filtrado (dim_calendario[Dia Útil] = "S").

### 4. CMV (Custo das Mercadorias Vendidas)
O CMV é calculado pelo método do inventário periódico:
**CMV = Estoque Inicial + Compras do período − Estoque Final**

- **vlr_estoque_inicial_compra**: Valor do estoque pelo preço de compra no início do mês (= estoque final do mês anterior).
- **vlr_estoque_final_compra**: Valor do estoque pelo preço de compra no final do mês, ajustado pelas movimentações ocorridas após o fim do mês.
- **vlr_compras_mes**: Valor total das entradas (compras) no mês = Σ vlr_total das NFs de entrada.
- **cmv_compra**: CMV calculado pelo preço de compra = EI_compra + Compras − EF_compra.
- **cmv_venda**: CMV calculado pelo preço de venda (para análise de margem sobre preço de venda).

### 5. PEDIDOS DE COMPRA
- **qtd_pedidos_comprados**: Quantidade total em aberto nos pedidos de compra (saldo_a_receber_cvt da tabela Produtos Convert).
- **qtd_pedidos_recebidos**: Quantidade já recebida dos pedidos (status = "Recebido").
- **saldo_a_receber**: Valor financeiro em aberto nos pedidos de compra.
- **ultimo_preco**: Último preço de compra pago pelo produto (pelo pedido mais recente).
- **estoque_adq**: Estoque atual + saldo a receber nos pedidos = posição total adquirida.

### 6. PREÇOS
- **max_preco_venda**: Preço de venda máximo atual do produto (dim_produtos).
- **max_preco_compra**: Preço de compra máximo atual do produto.
- **%_margem_estoque**: Margem calculada sobre o estoque = (Preço venda − Preço compra) / Preço venda.
- **vlr_custo_peso_compra**: Custo por kg com base no preço de compra e peso bruto do produto.

### 7. SIMULAÇÕES
- **qtd_estoque_cobertura_simulada**: Quantidade de estoque necessária para cobrir N meses (parâmetro configurável).
- **qtd_comprar_simulacao**: Quanto comprar de cada produto para atingir a cobertura desejada.
- **vlr_peso_compra**: Peso total a ser comprado na simulação.

---

## Regras de Negócio Importantes

### Meta de Vendas
A meta é definida mensalmente na tabela `Metas`. O acompanhamento é feito pelo `vlr_restante_meta`:
- **Positivo**: ainda falta para bater a meta
- **Negativo**: meta superada (boa notícia)
- **vlr_venda_media_util_dia** indica quanto precisa vender por dia útil para fechar no azul

### Saúde do Estoque
Produtos monitorados em 3 faixas de alerta:
- 30–60 dias sem venda → atenção
- 60–90 dias sem venda → preocupante
- +90 dias sem venda → crítico/obsoleto

Cobertura de estoque (`qtd_meses_capacidade_estoque`):
- < 2 meses sem pedido aberto → urgente comprar
- ≥ 2 meses → adequado
- Com pedido aberto → aguardando recebimento

### Margem Bruta
A meta de margem é definida pelo parâmetro `par_percent_margem`. Produtos com margem abaixo do parâmetro são destacados em `%_margem_bruta_par`.

### Caixa
- `fat_caixa` com status "E" = lançamentos efetivados (aconteceram)
- `fat_caixa` com status "A" = lançamentos abertos (previsões/pendências)
- **contas_a_pagar** e **contas_a_receber** são sempre status "A" (o que está pendente)

### Movimentações de Estoque
- `fat_movimento` com `tipo_movimento = "E"` e `stMov = "E"` = entrada efetiva de mercadoria
- `fat_movimento` com `tipo_movimento = "S"` e `stMov = "E"` = saída efetiva de mercadoria
- Movimentos com `stMov ≠ "E"` são pendentes/não efetivados
