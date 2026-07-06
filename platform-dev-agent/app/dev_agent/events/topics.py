"""Provisionamento dos tópicos Kafka v1 (ADR-012 D12.5).

`dataforall-kafka` roda com `AUTO_CREATE_TOPICS_ENABLE=false` — tópicos são criados
EXPLICITAMENTE. Um tópico por *aggregate*, com retenção diferenciada; chave de
partição = `tenant_id` (D12.6). Rode:

    python -m app.dev_agent.events.topics            # cria os 7 tópicos
    DEV_KAFKA_BOOTSTRAP=host:9095 python -m app.dev_agent.events.topics
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_DAY = 86_400_000
_YEAR = 365 * _DAY


@dataclass(frozen=True)
class TopicSpec:
    name: str
    partitions: int
    retention_ms: int
    cleanup_policy: str = "delete"    # delete | compact | "compact,delete"

    def kafka_config(self) -> dict[str, str]:
        return {"retention.ms": str(self.retention_ms), "cleanup.policy": self.cleanup_policy}


# Retenções da ADR-012 D12.5 (particionamento por tenant_id — 6 partições, ajustável).
TOPICS: tuple[TopicSpec, ...] = (
    TopicSpec("platform.plan.v1", 6, 30 * _DAY),
    TopicSpec("platform.approval.v1", 6, _YEAR, "compact,delete"),   # trilha de auditoria
    TopicSpec("platform.execution.v1", 6, 30 * _DAY),
    TopicSpec("platform.capability.v1", 6, 90 * _DAY),               # analytics de uso/custo
    TopicSpec("platform.policy.v1", 6, _YEAR),                       # auditoria de segurança
    TopicSpec("platform.delivery.v1", 6, _YEAR),
    TopicSpec("platform.asset.v1", 6, _YEAR),                        # governança de asset (ADR-014)
)


def provision(bootstrap_servers: str) -> dict[str, str]:
    """Cria os tópicos (idempotente: já-existe não é erro). Import LAZY do admin."""
    try:
        from kafka.admin import KafkaAdminClient, NewTopic  # type: ignore
        from kafka.errors import TopicAlreadyExistsError  # type: ignore
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("provision requer 'kafka-python' (pip install kafka-python)") from e

    admin = KafkaAdminClient(bootstrap_servers=bootstrap_servers)
    out: dict[str, str] = {}
    for spec in TOPICS:
        nt = NewTopic(name=spec.name, num_partitions=spec.partitions,
                      replication_factor=1, topic_configs=spec.kafka_config())
        try:
            admin.create_topics([nt])
            out[spec.name] = "created"
        except TopicAlreadyExistsError:
            out[spec.name] = "exists"
        except Exception as e:  # noqa: BLE001
            out[spec.name] = f"error: {e}"
    admin.close()
    return out


def main() -> int:
    boot = os.getenv("DEV_KAFKA_BOOTSTRAP", "localhost:9095")
    print(f"provisionando {len(TOPICS)} tópicos v1 em {boot} ...")
    for name, status in provision(boot).items():
        print(f"  {name}: {status}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
