from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.github import GitHubTokenVerifier


class OwnerVerifier(GitHubTokenVerifier):
    def __init__(self, owner_id):
        super().__init__(required_scopes=['read:user'])
        self.owner_id = str(owner_id)

    async def verify_token(self, token):
        result = await super().verify_token(token)
        if result is None or str(result.claims.get('sub')) != self.owner_id:
            return None
        return result


def build_auth(cfg):
    if not all([cfg.github_owner_id, cfg.github_client_id, cfg.github_client_secret.get_secret_value()]):
        raise ValueError('Configure GitHub OAuth credentials and owner numeric ID locally before hosting.')
    if not cfg.public_url.startswith('https://'):
        raise ValueError('PUBLIC_URL must be your public HTTPS origin.')
    from .state import SupabaseOAuthStore
    return OAuthProxy(
        client_storage=SupabaseOAuthStore(),
        upstream_authorization_endpoint='https://github.com/login/oauth/authorize',
        upstream_token_endpoint='https://github.com/login/oauth/access_token',
        upstream_client_id=cfg.github_client_id,
        upstream_client_secret=cfg.github_client_secret.get_secret_value(),
        token_verifier=OwnerVerifier(cfg.github_owner_id),
        base_url=cfg.public_url.rstrip('/'), valid_scopes=['read:user'],
        jwt_signing_key=cfg.github_client_secret.get_secret_value(),
        require_authorization_consent=True)
