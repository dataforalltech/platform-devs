"""
Services-MCP HTTP Endpoints — PostgreSQL Integration.

Endpoints para gerenciar service registry com health checks.
"""

from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class ServicesHTTPEndpoints:
    """HTTP endpoints para services-mcp com sync PostgreSQL."""

    def __init__(self, postgres_sync):
        """
        Initialize endpoints.

        Args:
            postgres_sync: ServicesPostgresSync instance
        """
        self.postgres_sync = postgres_sync

    # ========== GET /services ==========

    def get_services(self, environment: Optional[str] = None,
                     status: Optional[str] = None,
                     service_type: Optional[str] = None) -> Dict[str, Any]:
        """
        GET /services

        Lista serviços registrados com filtros opcionais.

        Query params:
            - environment: dev, staging, production
            - status: healthy, unhealthy, unknown, offline
            - type: mcp, api, docker, script, other

        Response (200):
            {
                "services": [
                    {
                        "id": 1,
                        "name": "platform-analytics",
                        "type": "docker",
                        "host": "localhost",
                        "port": 8001,
                        "status": "healthy",
                        "environment": "dev",
                        "health_check_url": "/health",
                        "last_health_check_at": "2026-05-10T10:29:45Z"
                    }
                ],
                "total": 18
            }
        """
        try:
            services = self.postgres_sync.list_services(
                environment=environment,
                status=status
            )

            if services is None:
                return {
                    'status': 500,
                    'error': 'database_error'
                }

            # Filter by type if specified
            if service_type:
                services = [s for s in services if s.get('type') == service_type]

            return {
                'status': 200,
                'services': [dict(s) for s in services],
                'total': len(services)
            }

        except Exception as e:
            logger.error(f"Error in GET /services: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /services/:name ==========

    def get_service(self, name: str) -> Dict[str, Any]:
        """
        GET /services/{name}

        Retorna detalhes de um serviço.

        Response (200):
            {
                "id": 1,
                "name": "platform-analytics",
                "type": "docker",
                "host": "localhost",
                "port": 8001,
                "description": "Analytics service",
                "status": "healthy",
                "environment": "dev",
                "health_check_url": "/health",
                "endpoint": "http://localhost:8001",
                "requires_auth": false,
                "version": "1.0.0",
                "last_health_check_at": "2026-05-10T10:29:45Z",
                "created_at": "2026-05-01T...",
                "updated_at": "2026-05-10T..."
            }

        Response (404):
            {
                "error": "service_not_found"
            }
        """
        try:
            service = self.postgres_sync.get_service(name)

            if service is None:
                return {
                    'status': 404,
                    'error': 'service_not_found'
                }

            return {
                'status': 200,
                **service  # Spread service dict
            }

        except Exception as e:
            logger.error(f"Error in GET /services/{name}: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== POST /services ==========

    def post_services(self, name: str, service_type: str, host: str,
                      port: int, health_check_url: Optional[str] = None,
                      **kwargs) -> Dict[str, Any]:
        """
        POST /services

        Registra novo serviço.

        Request:
            {
                "name": "platform-ml",
                "type": "docker",
                "host": "localhost",
                "port": 8005,
                "description": "Machine Learning service",
                "health_check_url": "/health",
                "environment": "dev",
                "requires_auth": false
            }

        Response (201):
            {
                "id": 19,
                "name": "platform-ml",
                "status": "unknown",
                "created_at": "2026-05-10T10:30:45Z"
            }

        Response (409):
            {
                "error": "service_already_exists"
            }
        """
        try:
            # Step 1: Check if already exists
            existing = self.postgres_sync.get_service(name)
            if existing:
                return {
                    'status': 409,
                    'error': 'service_already_exists'
                }

            # Step 2: Register in PostgreSQL
            service_data = {
                'name': name,
                'type': service_type,
                'host': host,
                'port': port,
                'health_check_url': health_check_url,
                'description': kwargs.get('description'),
                'environment': kwargs.get('environment', 'dev'),
                'requires_auth': kwargs.get('requires_auth', False),
            }

            self.postgres_sync.sync_service_registered(service_data)

            # Step 3: Log audit trail
            self.postgres_sync.log_action(
                action='register',
                service_name=name,
                details=service_data
            )

            logger.info(f"✅ Service registered: {name}")

            return {
                'status': 201,
                'id': None,  # Would be returned from PostgreSQL insert
                'name': name,
                'status': 'unknown',
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in POST /services: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== PATCH /services/:name ==========

    def patch_service(self, name: str, **updates) -> Dict[str, Any]:
        """
        PATCH /services/{name}

        Atualiza metadados de um serviço.

        Request:
            {
                "description": "New description",
                "health_check_url": "/healthz",
                "requires_auth": true
            }

        Response (200):
            {
                "updated": true,
                "updated_at": "2026-05-10T10:30:45Z"
            }

        Response (404):
            {
                "error": "service_not_found"
            }
        """
        try:
            # Step 1: Check if exists
            service = self.postgres_sync.get_service(name)
            if service is None:
                return {
                    'status': 404,
                    'error': 'service_not_found'
                }

            # Step 2: Update in PostgreSQL
            self.postgres_sync.sync_service_updated(name, updates)

            # Step 3: Log audit trail
            self.postgres_sync.log_action(
                action='update',
                service_name=name,
                details=updates
            )

            logger.info(f"✅ Service updated: {name}")

            return {
                'status': 200,
                'updated': True,
                'updated_at': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in PATCH /services/{name}: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /services/health ==========

    def get_services_health(self) -> Dict[str, Any]:
        """
        GET /services/health

        Retorna resumo de saúde de todos os serviços.

        Response (200):
            {
                "healthy": 16,
                "unhealthy": 2,
                "unknown": 0,
                "total": 18,
                "unhealthy_services": [
                    {
                        "name": "platform-monitor",
                        "status": "unhealthy",
                        "last_health_check_at": "2026-05-10T10:29:00Z"
                    }
                ]
            }
        """
        try:
            all_services = self.postgres_sync.list_services()
            if all_services is None:
                return {
                    'status': 500,
                    'error': 'database_error'
                }

            unhealthy = self.postgres_sync.list_unhealthy_services()

            healthy = sum(1 for s in all_services if s.get('status') == 'healthy')
            unhealthy_count = len(unhealthy) if unhealthy else 0
            unknown = sum(1 for s in all_services if s.get('status') == 'unknown')

            return {
                'status': 200,
                'healthy': healthy,
                'unhealthy': unhealthy_count,
                'unknown': unknown,
                'total': len(all_services),
                'unhealthy_services': [dict(s) for s in (unhealthy or [])]
            }

        except Exception as e:
            logger.error(f"Error in GET /services/health: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== POST /services/:name/health-check ==========

    def post_service_health_check(self, name: str, status: str,
                                  response_time_ms: Optional[float] = None) -> Dict[str, Any]:
        """
        POST /services/{name}/health-check

        Registra resultado de health check.

        Request:
            {
                "status": "healthy",
                "response_time_ms": 25.5
            }

        Response (200):
            {
                "updated": true,
                "status": "healthy",
                "timestamp": "2026-05-10T10:30:45Z"
            }
        """
        try:
            # Step 1: Check if exists
            service = self.postgres_sync.get_service(name)
            if service is None:
                return {
                    'status': 404,
                    'error': 'service_not_found'
                }

            # Step 2: Update status in PostgreSQL
            self.postgres_sync.sync_health_check_result(
                name,
                status=status,
                response_time_ms=response_time_ms
            )

            # Step 3: Log audit trail
            self.postgres_sync.log_action(
                action='health_check',
                service_name=name,
                details={
                    'status': status,
                    'response_time_ms': response_time_ms
                }
            )

            logger.debug(f"✅ Health check recorded: {name} → {status}")

            return {
                'status': 200,
                'updated': True,
                'service_status': status,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in POST /services/{name}/health-check: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== DELETE /services/:name ==========

    def delete_service(self, name: str) -> Dict[str, Any]:
        """
        DELETE /services/{name}

        Remove um serviço do registry.

        Response (200):
            {
                "deleted": true,
                "timestamp": "2026-05-10T10:30:45Z"
            }

        Response (404):
            {
                "error": "service_not_found"
            }
        """
        try:
            # Step 1: Check if exists
            service = self.postgres_sync.get_service(name)
            if service is None:
                return {
                    'status': 404,
                    'error': 'service_not_found'
                }

            # Step 2: Remove from PostgreSQL
            self.postgres_sync.sync_service_removed(name)

            # Step 3: Log audit trail
            self.postgres_sync.log_action(
                action='unregister',
                service_name=name,
                details={}
            )

            logger.info(f"✅ Service removed: {name}")

            return {
                'status': 200,
                'deleted': True,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in DELETE /services/{name}: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }
