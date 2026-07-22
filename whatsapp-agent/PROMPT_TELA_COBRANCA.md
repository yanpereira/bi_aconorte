# Prompt — Tela de Cobrança (Inadimplentes) via MinIO

Copie o conteúdo abaixo para a IA/aplicação que vai construir a tela de cobrança.

---

## Contexto

Você vai construir uma **tela de cobrança** que lista os clientes **inadimplentes**:
contas a receber que estão **em aberto** (ainda não pagas) e cuja **data de vencimento já passou**.
Os dados vêm **diretamente do MinIO** (S3-compatible), em arquivos Parquet — não use Power BI.

## Conexão com o MinIO

Use as mesmas credenciais/variáveis já usadas no projeto (arquivo `.env` do `whatsapp-agent`):

```
SAVE_MINIO_COPY=true
MINIO_ENDPOINT=elt-minio.xbgiwf.easypanel.host
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=password
MINIO_SECURE=true
MINIO_CERT_CHECK=false
MINIO_BUCKET=aconorte
MINIO_PREFIX=
```

Objetos são lidos com `pandas.read_parquet` a partir dos bytes do objeto (biblioteca `minio` + `io.BytesIO`).
Se `MINIO_PREFIX` estiver definido, o nome final do objeto é `f"{MINIO_PREFIX}/{nome}"`.

## Arquivos (tabelas) relevantes no bucket

| Arquivo | Conteúdo |
|---|---|
| `caixa.parquet` | Lançamentos financeiros (contas a pagar e a receber), um registro por parcela/título |
| `dim_pessoas.parquet` | Cadastro de clientes/pessoas (nome, telefone, cidade etc.) |

### `caixa.parquet` — colunas

| Coluna | Tipo | Significado |
|---|---|---|
| `idConta` | inteiro | ID do título/lançamento |
| `ds_sistema` | texto | Sistema de origem do lançamento |
| `tpOrigem` | texto | Tipo de origem do lançamento |
| `tipo` | texto | **`C`** = Contas a Receber, **`D`** = Contas a Pagar |
| `status` | texto | **`A`** = Aberto (pendente), demais valores = já efetivado/baixado. ⚠️ **Confirme os valores reais** lendo `caixa["status"].unique()` antes de fixar a regra — no código atual do projeto já foi visto tanto `"A"`/`"E"` quanto `"A"`/`"P"` sendo usados para "aberto"/"efetivado", então trate como texto e valide na base real. |
| `idOrigem` | número | ID de origem (ex.: venda) |
| `cd_pessoa` (ou `idPessoa`) | inteiro | Cliente — chave para juntar com `dim_pessoas.parquet`. **Confirme o nome exato da coluna no arquivo real**, pois no modelo há as duas variações (`cd_pessoa` após renomeação, `idPessoa` na origem crua). |
| `parcela` | inteiro | Número da parcela |
| `qtdeParcelas` | inteiro | Total de parcelas do título |
| `codContasCaixa` | texto | Código do título |
| `historico` | texto | Descrição/histórico do lançamento (pode conter referência à venda) |
| `caixaLancamento` | inteiro | ID do lançamento no caixa |
| `dtLancamento` | data | Data em que o lançamento foi criado |
| `dtVencimento` | data | **Data de vencimento do título** — base da inadimplência |
| `valor` | decimal (R$) | Valor original do título |
| `valDesconto` | decimal (R$) | Desconto concedido |
| `valMulta` | decimal (R$) | Multa por atraso |
| `valJuros` | decimal (R$) | Juros por atraso |
| `valTaxa` | decimal (R$) | Taxa adicional |
| `caixaBaixa` | inteiro | ID da baixa (quitação), se houver |
| `dtBaixa` | data | Data em que o título foi baixado/pago (vazio = ainda em aberto) |
| `codTipoPg` | texto | Tipo de pagamento (código) |
| `valBaixa` | decimal (R$) | Valor efetivamente pago na baixa |
| `motivoExtorno` | texto | Motivo de estorno, se houve |
| `numeroBoleto` | número | Número do boleto emitido |

### `dim_pessoas.parquet` — colunas relevantes

| Coluna | Significado |
|---|---|
| `cd_pessoa` | ID do cliente — chave de junção com `caixa.parquet` |
| `ds_pessoa` | Nome do cliente |
| `telefone` | Telefone (use para contato via WhatsApp) |
| `ds_endereco` / `ds_cidade` / `UF` | Endereço |
| `flag_cliente` | Indica se é cliente (vs. fornecedor/transportador/vendedor) |

## Regra de negócio — o que é "inadimplente / título vencido em aberto"

Um título entra na tela de cobrança quando **todas** as condições abaixo são verdadeiras:

1. `tipo == "C"` → é conta a **receber** (não conta a pagar)
2. `status` indica **em aberto** (não baixado) — normalmente `"A"`; confirme na base real
3. `dtVencimento` **não é nulo** e é **menor que a data de hoje** (`dtVencimento < hoje`)
4. (equivalente/reforço) `dtBaixa` está vazio/nulo — título ainda não foi pago

Calcule os dias de atraso assim (mesma lógica usada no modelo semântico, medida/coluna `dias_atraso`):

```python
dias_atraso = (hoje - dtVencimento).days  # apenas quando dtVencimento < hoje, senão 0
```

Valor total devido do título (sugestão, ajuste conforme a regra de cobrança da empresa):

```
valor_devido = valor + valMulta + valJuros + valTaxa - valDesconto
```

## O que a tela deve mostrar

Uma lista/tabela de títulos vencidos em aberto, uma linha por parcela, com:

- Cliente (`ds_pessoa`) e telefone (`telefone`) — para contato
- Valor original (`valor`) e valor devido calculado (`valor_devido`)
- Data de vencimento (`dtVencimento`) e dias de atraso (`dias_atraso`)
- Parcela / total de parcelas (`parcela` de `qtdeParcelas`)
- Número do boleto (`numeroBoleto`), se houver
- Histórico/descrição (`historico`)

Sugestões de agregados no topo da tela:
- Valor total em aberto vencido (soma de `valor_devido`)
- Quantidade de clientes inadimplentes distintos
- Quantidade de títulos vencidos
- Ranking dos clientes com maior valor em atraso e/ou maior número de dias de atraso

## Passo a passo sugerido para implementação

1. Conectar no MinIO com as credenciais acima.
2. Ler `caixa.parquet` e `dim_pessoas.parquet` com `pandas.read_parquet`.
3. Inspecionar `caixa["status"].unique()` e o nome real da coluna de cliente (`cd_pessoa` vs `idPessoa`) antes de aplicar os filtros — os nomes podem variar conforme a etapa do pipeline que gerou o parquet.
4. Filtrar: `tipo == "C"` e `status` em aberto e `dtVencimento < hoje` (e/ou `dtBaixa` nulo).
5. Calcular `dias_atraso` e `valor_devido`.
6. Fazer merge com `dim_pessoas` por `cd_pessoa` para trazer nome e telefone.
7. Ordenar por `dias_atraso` (desc) ou `valor_devido` (desc) para priorizar a cobrança.
8. Exibir na tela / disponibilizar como endpoint para o app de cobrança.
