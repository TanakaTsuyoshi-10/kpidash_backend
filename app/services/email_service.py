"""
メール送信サービス（Resend）

Resend の HTTPS API を httpx で呼び出すシンプルなトランザクションメール送信。
RESEND_API_KEY 未設定時は送信せずログのみ（開発環境向けサンプルモード）。
"""
import logging
from typing import List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"
API_TIMEOUT = 10.0


def email_enabled() -> bool:
    """メール送信が有効か（RESEND_API_KEY が設定されているか）"""
    return bool(getattr(settings, "RESEND_API_KEY", ""))


async def send_email(
    to: List[str],
    subject: str,
    html: str,
) -> bool:
    """
    メールを1通送信する。

    Returns:
        bool: 送信成功なら True。未設定/失敗時は False（例外は投げない）
    """
    if not to:
        return False

    if not email_enabled():
        logger.info("[email sample-mode] to=%s subject=%s", to, subject)
        return True  # 開発環境では成功扱い（notified_at を進めて多重送信を防ぐ）

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            res = await client.post(
                RESEND_API_URL,
                headers={
                    "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": settings.RESEND_FROM_ADDRESS,
                    "to": to,
                    "subject": subject,
                    "html": html,
                },
            )
            if res.status_code in (200, 201):
                return True
            logger.warning(
                "Resend 送信失敗: status=%s body=%s", res.status_code, res.text[:300]
            )
            return False
    except Exception as exc:
        logger.warning("Resend 送信例外: %s", exc)
        return False


def _approval_url(request_id: str) -> str:
    base = getattr(settings, "APP_BASE_URL", "") or "https://kpidash-frontend.vercel.app"
    return f"{base.rstrip('/')}/approvals/{request_id}"


async def send_approval_request_email(
    to_email: str,
    requester_name: str,
    type_label: str,
    title: str,
    preview_text: str,
    request_id: str,
) -> bool:
    """申請時: 承認者への承認依頼メール"""
    url = _approval_url(request_id)
    subject = f"【承認依頼】{title}"
    html = f"""
    <div style="font-family: sans-serif; max-width: 560px;">
      <h2 style="color: #1f2937;">承認依頼が届いています</h2>
      <table style="border-collapse: collapse; width: 100%; margin: 16px 0;">
        <tr><td style="padding: 6px 12px; color: #6b7280;">申請者</td><td style="padding: 6px 12px;">{requester_name}</td></tr>
        <tr><td style="padding: 6px 12px; color: #6b7280;">種別</td><td style="padding: 6px 12px;">{type_label}</td></tr>
        <tr><td style="padding: 6px 12px; color: #6b7280;">タイトル</td><td style="padding: 6px 12px;">{title}</td></tr>
      </table>
      <p style="color: #374151; background: #f9fafb; padding: 12px; border-radius: 8px;">{preview_text}</p>
      <a href="{url}" style="display: inline-block; background: #2563eb; color: #fff; padding: 10px 24px; border-radius: 8px; text-decoration: none; margin-top: 16px;">承認画面を開く</a>
      <p style="color: #9ca3af; font-size: 12px; margin-top: 24px;">このメールは ぎょうざの丸岡 KPI管理システムから自動送信されています。</p>
    </div>
    """
    return await send_email([to_email], subject, html)


async def send_reject_email(
    to_email: str,
    approver_name: str,
    title: str,
    comment: Optional[str],
    request_id: str,
) -> bool:
    """却下時: 申請者への通知メール（Phase1 では設定により送信）"""
    url = _approval_url(request_id)
    subject = f"【却下】{title}"
    comment_html = f'<p style="color: #374151; background: #fef2f2; padding: 12px; border-radius: 8px;">{comment}</p>' if comment else ""
    html = f"""
    <div style="font-family: sans-serif; max-width: 560px;">
      <h2 style="color: #b91c1c;">申請が却下されました</h2>
      <p>{approver_name} さんが「{title}」を却下しました。</p>
      {comment_html}
      <a href="{url}" style="display: inline-block; background: #6b7280; color: #fff; padding: 10px 24px; border-radius: 8px; text-decoration: none; margin-top: 16px;">詳細を確認する</a>
    </div>
    """
    return await send_email([to_email], subject, html)


async def send_delegation_email(
    to_emails: List[str],
    original_name: str,
    delegate_name: str,
    title: str,
    request_id: str,
) -> bool:
    """代理切替時: 委任元・委任先への通知メール"""
    url = _approval_url(request_id)
    subject = f"【代理承認】{title}"
    html = f"""
    <div style="font-family: sans-serif; max-width: 560px;">
      <h2 style="color: #1f2937;">承認が代理承認者へ切り替わりました</h2>
      <p>「{title}」の承認担当が {original_name} さんから {delegate_name} さんへ切り替わりました（不在期間の代理設定による自動切替）。</p>
      <a href="{url}" style="display: inline-block; background: #2563eb; color: #fff; padding: 10px 24px; border-radius: 8px; text-decoration: none; margin-top: 16px;">承認画面を開く</a>
    </div>
    """
    return await send_email(to_emails, subject, html)
