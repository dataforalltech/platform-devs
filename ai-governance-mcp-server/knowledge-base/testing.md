# Testes

Testes existem para detectar regressão. Nunca apague para fazer build passar.

## Pode

- Usar fakes/stubs para serviços externos em testes unitários.
- Testes de integração com banco/serviço real em containers efêmeros (testcontainers).
- Snapshot tests para contratos estáveis.
- Testes parametrizados para varrer casos.

## Não pode

- Apagar teste para fazer build passar.
- Marcar `@pytest.mark.skip` permanentemente sem ADR.
- Mockar o sistema sob teste (mocking the unit under test).
- Teste dependente de ordem (pular ordem aleatória → assume `pytest -p random_order` ok).
- `time.sleep` arbitrário em teste (usar tempo virtual ou polling com timeout).

## Errado

```python
# Skip permanente sem owner
@pytest.mark.skip("flaky")
def test_payment_flow(): ...

# Mockando o que está sendo testado
def test_calc_total():
    mock.patch("myapp.OrderService.calc_total")  # mockou o próprio teste
    ...

# Apagar teste para verde no CI
# (sem teste, sem regressão visível, bug volta)
```

## Correto

```python
# Teste de regressão para bug específico
def test_calc_total_with_zero_items_regression_1234():
    """Regression: bug #1234 — calc_total quebrava com lista vazia."""
    assert OrderService().calc_total(items=[]) == Decimal("0")

# Integração com Postgres real via testcontainers
def test_repository_query_persists(pg_container):
    repo = OrderRepository(pg_container.url)
    repo.save(order)
    assert repo.find(order.id) == order

# Mock só nas bordas
def test_create_order_when_provider_fails():
    fake_provider = FakeProvider(raises=ProviderTimeout)
    service = OrderService(provider=fake_provider)
    with pytest.raises(ProviderUnavailable):
        service.create(payload)
```

## Bugfix sem teste é incompleto

Toda correção de bug precisa de **teste de regressão**:

- O teste deve falhar **antes** do fix.
- O teste deve passar **depois** do fix.
- Nome do teste cita o ticket/issue: `test_X_regression_<id>`.

## Testes determinísticos

- Sem `time.sleep` arbitrário → use `freezegun`/`time-machine` ou polling com timeout.
- Sem dependência de ordem → testes devem passar em ordem aleatória.
- Sem dependência de rede externa → containers locais ou stubs.
- Sem dependência de relógio do sistema → injete clock.

## Cobertura

Cobertura é **resultado**, não meta. Mire em:

- 100% dos caminhos críticos (pagamento, autenticação, autorização).
- Caminho de erro de cada integração externa.
- Cada constraint de banco que faz parte do contrato.
