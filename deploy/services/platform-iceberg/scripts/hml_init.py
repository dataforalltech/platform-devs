"""
hml_init.py — configura catalog Polaris, cria schema gold e faz seed de dados HML

Executado a cada 'docker compose up' pelo serviço hml-init.
Idempotente em ambos os modos de persistência do Polaris:

  in-memory (padrão):
    O estado é recriado do zero a cada restart; hml-init cria tudo.

  relational-jdbc (PostgreSQL persistente):
    O estado sobrevive a restarts; hml-init verifica via GET se o catalog
    já existe e pula a criação caso positivo. As operações Trino usam
    CREATE IF NOT EXISTS / INSERT só se vazio, portanto são sempre seguras.
"""

import os
import sys
import time

import requests
import trino

POLARIS_URL    = "http://polaris:8181"
POLARIS_ID     = os.environ.get("POLARIS_CLIENT_ID",     "root")
POLARIS_SECRET = os.environ.get("POLARIS_CLIENT_SECRET", "")
TRINO_HOST     = os.environ.get("TRINO_HOST", "trino")
TRINO_PORT     = int(os.environ.get("TRINO_PORT", "8080"))
CATALOG        = "tenant_lab_s3"
SCHEMA         = "gold"


# ── helpers ────────────────────────────────────────────────────────────────

def polaris_get(path, token):
    headers = {"Authorization": f"Bearer {token}"}
    r = requests.get(f"{POLARIS_URL}{path}", headers=headers, timeout=30)
    print(f"  GET  {path} → HTTP {r.status_code}")
    return r


def polaris_post(path, token, json=None):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.post(f"{POLARIS_URL}{path}", headers=headers, json=json, timeout=30)
    print(f"  POST {path} → HTTP {r.status_code}")
    return r


def polaris_put(path, token, json):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    r = requests.put(f"{POLARIS_URL}{path}", headers=headers, json=json, timeout=30)
    print(f"  PUT  {path} → HTTP {r.status_code}")
    return r


def run_sql(desc, sql, retries=5, wait=10):
    """Executa SQL no Trino com retry. Retorna resultado."""
    for attempt in range(1, retries + 1):
        try:
            conn = trino.dbapi.connect(host=TRINO_HOST, port=TRINO_PORT, user="hml-init")
            cur = conn.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            print(f"  ✓ {desc}")
            return rows
        except Exception as exc:
            print(f"  tentativa {attempt}/{retries} ({desc}): {exc}")
            if attempt < retries:
                time.sleep(wait)
    print(f"  ERRO: {desc} falhou após {retries} tentativas")
    sys.exit(1)


def count(table):
    rows = run_sql(f"COUNT {table}", f"SELECT COUNT(*) FROM {CATALOG}.{SCHEMA}.{table}")
    return rows[0][0] if rows else 0


# ── step 1: token Polaris ──────────────────────────────────────────────────

print("=== [hml-init] Obtendo token Polaris ===")
token = None
for attempt in range(1, 11):
    try:
        r = requests.post(
            f"{POLARIS_URL}/api/catalog/v1/oauth/tokens",
            data={
                "grant_type":    "client_credentials",
                "client_id":     POLARIS_ID,
                "client_secret": POLARIS_SECRET,
                "scope":         "PRINCIPAL_ROLE:ALL",
            },
            timeout=10,
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        print(f"  token obtido na tentativa {attempt}")
        break
    except Exception as exc:
        print(f"  tentativa {attempt}/10 falhou: {exc}")
        time.sleep(5)

if not token:
    print("ERRO: não foi possível obter token Polaris")
    sys.exit(1)

# ── step 2: catalog ────────────────────────────────────────────────────────
# Verifica via GET se o catalog já existe (Polaris persistente retorna 200;
# in-memory após restart retorna 404). Cria apenas se necessário.

print(f"=== [hml-init] Verificando catalog {CATALOG} no Polaris ===")
r_check = polaris_get(f"/api/management/v1/catalogs/{CATALOG}", token)

if r_check.status_code == 200:
    print(f"  → catalog '{CATALOG}' já existe (Polaris persistente) — pulando criação")
else:
    print(f"=== [hml-init] Criando catalog {CATALOG} no Polaris ===")
    polaris_post("/api/management/v1/catalogs", token, json={
        "name": CATALOG,
        "type": "INTERNAL",
        "properties": {"default-base-location": f"s3://warehouse/{CATALOG}"},
        "storageConfigInfo": {
            "storageType":      "S3",
            "allowedLocations": ["s3://warehouse/"],
            "roleArn":          "arn:aws:iam::000000000000:role/hml",
            "pathStyleAccess":  True,
        },
    })

    print("=== [hml-init] Criando catalog role ===")
    polaris_post(f"/api/management/v1/catalogs/{CATALOG}/catalog-roles", token,
                 json={"name": "catalog_admin"})

    print("=== [hml-init] Concedendo CATALOG_MANAGE_CONTENT ===")
    polaris_put(f"/api/management/v1/catalogs/{CATALOG}/catalog-roles/catalog_admin/grants", token,
                json={"type": "catalog", "privilege": "CATALOG_MANAGE_CONTENT"})

    print("=== [hml-init] Atribuindo role ao service_admin ===")
    polaris_put(f"/api/management/v1/principal-roles/service_admin/catalog-roles/{CATALOG}", token,
                json={"name": "catalog_admin"})

# ── step 3: schema gold ────────────────────────────────────────────────────

print("=== [hml-init] Criando schema gold via Trino ===")
run_sql("CREATE SCHEMA gold", f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}")

# ── step 4: tabelas ────────────────────────────────────────────────────────

print("=== [hml-init] Criando tabelas Iceberg ===")

run_sql("CREATE TABLE clientes", f"""
    CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.clientes (
        id          INTEGER,
        nome        VARCHAR,
        email       VARCHAR,
        cidade      VARCHAR,
        created_at  TIMESTAMP
    ) WITH (format = 'PARQUET')
""")

run_sql("CREATE TABLE produtos", f"""
    CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.produtos (
        id         INTEGER,
        nome       VARCHAR,
        categoria  VARCHAR,
        preco      DOUBLE,
        estoque    INTEGER
    ) WITH (format = 'PARQUET')
""")

run_sql("CREATE TABLE pedidos", f"""
    CREATE TABLE IF NOT EXISTS {CATALOG}.{SCHEMA}.pedidos (
        id           INTEGER,
        cliente_id   INTEGER,
        produto_id   INTEGER,
        quantidade   INTEGER,
        valor_total  DOUBLE,
        status       VARCHAR,
        data_pedido  TIMESTAMP
    ) WITH (format = 'PARQUET')
""")

# ── step 5: seed (idempotente — só insere se a tabela estiver vazia) ───────

print("=== [hml-init] Seed de dados ===")

if count("clientes") == 0:
    run_sql("INSERT clientes", f"""
        INSERT INTO {CATALOG}.{SCHEMA}.clientes VALUES
        (1,  'Ana Silva',       'ana@email.com',     'São Paulo',       TIMESTAMP '2024-01-10 09:00:00'),
        (2,  'Bruno Costa',     'bruno@email.com',   'Rio de Janeiro',  TIMESTAMP '2024-01-15 10:30:00'),
        (3,  'Carla Mendes',    'carla@email.com',   'Curitiba',        TIMESTAMP '2024-02-01 11:00:00'),
        (4,  'Diego Ferreira',  'diego@email.com',   'Belo Horizonte',  TIMESTAMP '2024-02-10 14:00:00'),
        (5,  'Elena Santos',    'elena@email.com',   'Porto Alegre',    TIMESTAMP '2024-02-20 08:00:00'),
        (6,  'Felipe Lima',     'felipe@email.com',  'Fortaleza',       TIMESTAMP '2024-03-01 09:30:00'),
        (7,  'Gabriela Rocha',  'gabi@email.com',    'Salvador',        TIMESTAMP '2024-03-05 10:00:00'),
        (8,  'Hugo Alves',      'hugo@email.com',    'Manaus',          TIMESTAMP '2024-03-10 15:00:00'),
        (9,  'Isabela Nunes',   'isa@email.com',     'Recife',          TIMESTAMP '2024-03-15 11:30:00'),
        (10, 'João Pereira',    'joao@email.com',    'Brasília',        TIMESTAMP '2024-03-20 16:00:00')
    """)
else:
    print("  → clientes já tem dados, pulando")

if count("produtos") == 0:
    run_sql("INSERT produtos", f"""
        INSERT INTO {CATALOG}.{SCHEMA}.produtos VALUES
        (1,  'Notebook Pro',       'Eletrônicos',   4500.00, 30),
        (2,  'Mouse Sem Fio',      'Periféricos',    120.00, 150),
        (3,  'Teclado Mecânico',   'Periféricos',    350.00, 80),
        (4,  'Monitor 27"',        'Eletrônicos',   1800.00, 25),
        (5,  'Headset Gamer',      'Periféricos',    280.00, 60),
        (6,  'SSD 1TB',            'Armazenamento',  400.00, 90),
        (7,  'Webcam Full HD',     'Periféricos',    200.00, 45),
        (8,  'Hub USB-C',          'Acessórios',      80.00, 120),
        (9,  'Suporte Notebook',   'Acessórios',     150.00, 70),
        (10, 'Cadeira Ergonômica', 'Mobiliário',    1200.00, 15),
        (11, 'Mesa Escritório',    'Mobiliário',     800.00, 10),
        (12, 'Luminária LED',      'Acessórios',      90.00, 100),
        (13, 'Impressora Laser',   'Eletrônicos',   1100.00, 20),
        (14, 'Tablet 10"',         'Eletrônicos',   1500.00, 35),
        (15, 'Caixa de Som BT',    'Áudio',          250.00, 55)
    """)
else:
    print("  → produtos já tem dados, pulando")

if count("pedidos") == 0:
    run_sql("INSERT pedidos (base)", f"""
        INSERT INTO {CATALOG}.{SCHEMA}.pedidos VALUES
        (1,  1, 1,  1,  4500.00, 'entregue',    TIMESTAMP '2024-04-01 10:00:00'),
        (2,  2, 2,  2,   240.00, 'entregue',    TIMESTAMP '2024-04-02 11:00:00'),
        (3,  3, 5,  1,   280.00, 'entregue',    TIMESTAMP '2024-04-03 09:00:00'),
        (4,  4, 3,  1,   350.00, 'entregue',    TIMESTAMP '2024-04-04 14:00:00'),
        (5,  5, 4,  1,  1800.00, 'entregue',    TIMESTAMP '2024-04-05 08:30:00'),
        (6,  6, 6,  2,   800.00, 'entregue',    TIMESTAMP '2024-04-06 15:00:00'),
        (7,  7, 7,  1,   200.00, 'enviado',     TIMESTAMP '2024-04-07 10:30:00'),
        (8,  8, 8,  3,   240.00, 'enviado',     TIMESTAMP '2024-04-08 11:30:00'),
        (9,  9, 9,  1,   150.00, 'enviado',     TIMESTAMP '2024-04-09 09:30:00'),
        (10, 10,10, 1,  1200.00, 'enviado',     TIMESTAMP '2024-04-10 16:00:00'),
        (11, 1, 11, 1,   800.00, 'processando', TIMESTAMP '2024-04-11 10:00:00'),
        (12, 2, 12, 2,   180.00, 'processando', TIMESTAMP '2024-04-12 11:00:00'),
        (13, 3, 13, 1,  1100.00, 'processando', TIMESTAMP '2024-04-13 09:00:00'),
        (14, 4, 14, 1,  1500.00, 'pendente',    TIMESTAMP '2024-04-14 14:00:00'),
        (15, 5, 15, 2,   500.00, 'pendente',    TIMESTAMP '2024-04-15 08:30:00'),
        (16, 6, 1,  1,  4500.00, 'pendente',    TIMESTAMP '2024-04-16 15:00:00'),
        (17, 7, 2,  5,   600.00, 'pendente',    TIMESTAMP '2024-04-17 10:30:00'),
        (18, 8, 3,  1,   350.00, 'cancelado',   TIMESTAMP '2024-04-18 11:30:00'),
        (19, 9, 4,  1,  1800.00, 'cancelado',   TIMESTAMP '2024-04-19 09:30:00'),
        (20, 10,5,  1,   280.00, 'cancelado',   TIMESTAMP '2024-04-20 16:00:00')
    """)
else:
    print("  → pedidos já tem dados, pulando")

# ── step 6: volume 1MM pedidos ─────────────────────────────────────────────
# Multiplica as linhas base via CROSS JOIN com sequence do Trino.
# Idempotente: pula se já atingiu o alvo.
# Matemática: 20 linhas × (1 base + 49.999 cópias) = 1.000.000 exatas.

# sequence(1, 499): 20 linhas base × 499 = 9.980 → total 10.000
VOLUME_TARGET = 10_000

print(f"=== [hml-init] Volume {VOLUME_TARGET:,} pedidos ===")
n_ped = count("pedidos")

if n_ped >= VOLUME_TARGET:
    print(f"  → pedidos já tem {n_ped:,} linhas, pulando")
elif n_ped == 0:
    print("  ERRO: seed base falhou — abortando volume")
    sys.exit(1)
else:
    print(f"  → {n_ped} linhas base × 499 = {n_ped * 499:,} → total {n_ped + n_ped * 499:,} linhas")
    run_sql(
        "VOLUME pedidos 10k (20×499)",
        f"""
        INSERT INTO {CATALOG}.{SCHEMA}.pedidos
        SELECT id, cliente_id, produto_id, quantidade, valor_total, status, data_pedido
        FROM   {CATALOG}.{SCHEMA}.pedidos
        CROSS JOIN UNNEST(sequence(1, 499)) t(n)
        WHERE  id BETWEEN 1 AND 20
        """,
        retries=2,
        wait=30,
    )

# ── resumo ─────────────────────────────────────────────────────────────────

n_cli = count("clientes")
n_pro = count("produtos")
n_ped = count("pedidos")
print(f"=== [hml-init] Pronto — clientes={n_cli}, produtos={n_pro}, pedidos={n_ped:,} ===")
