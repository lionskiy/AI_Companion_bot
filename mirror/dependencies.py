"""
Singleton-инстансы всех сервисов.
Импортировать отсюда — не создавать сервисы в handlers напрямую.
"""

# Заглушки — заменяются реальными классами по мере реализации модулей.
# Каждый модуль реализует свой класс и подставляет его здесь.

llm_router = None          # Module 05: mirror.core.llm.router.LLMRouter
memory_service = None      # Module 03: mirror.core.memory.service.MemoryService
identity_service = None    # Module 01: mirror.core.identity.service.IdentityService
billing_service = None     # Module 10: mirror.services.billing.BillingService
policy_engine = None       # Module 04: mirror.core.policy.safety.PolicyEngine
dialog_service = None      # Module 06: mirror.services.dialog.DialogService
astrology_service = None   # Module 07: mirror.services.astrology.AstrologyService
tarot_service = None       # Module 08: mirror.services.tarot.TarotService
daily_ritual_service = None  # Module 09: mirror.services.daily_ritual.DailyRitualService
telegram_adapter = None    # Module 02: mirror.channels.telegram.adapter.TelegramAdapter
