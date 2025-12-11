function parseJwt(token) {
    try {
        const base64Url = token.split('.')[1];
        const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
        const jsonPayload = decodeURIComponent(atob(base64).split('').map(function (c) {
            return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
        }).join(''));
        return JSON.parse(jsonPayload);
    } catch (e) {
        return null;
    }
}

function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
}

async function checkDjangoSession() {
    try {
        const response = await fetch(window.location.pathname, {
            method: 'GET',
            credentials: 'include',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });

        if (response.ok) {
            return true;
        }

        if (response.status === 302) {
            window.location.replace(window.LOGIN_URL);
            return false;
        }
    } catch (e) {
        return true;
    }

    return false;
}

async function handleNoTokens() {
    const sessionValid = await checkDjangoSession();
    if (sessionValid) {
        return true;
    }

    try {
        const response = await fetch('/authentication/token/session/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        });

        if (response.ok) {
            return true;
        }
    } catch (e) {
    }
    return false;
}

async function handleInvalidToken() {
    const sessionValid = await checkDjangoSession();
    if (sessionValid) {
        return true;
    }

    try {
        const response = await fetch('/authentication/token/refresh/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        });

        if (response.ok) {
            return true;
        }
    } catch (e) {
    }
    return false;
}

async function handleExpiringToken(secondsLeft) {
    if (secondsLeft > 30) {
        return true;
    }

    try {
        const resp = await fetch('/authentication/token/refresh/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        });
        if (resp.ok) {
            return true;
        }
    } catch (e) {
    }

    return await checkDjangoSession();
}

async function ensureValidAccessToken() {
    const access = getCookie('access_token');
    const refresh = getCookie('refresh_token');

    if (!access || !refresh) {
        return await handleNoTokens();
    }

    const payload = parseJwt(access);
    if (!payload || !payload.exp) {
        return await handleInvalidToken();
    }

    const now = Math.floor(Date.now() / 1000);
    const secondsLeft = payload.exp - now;

    return await handleExpiringToken(secondsLeft);
}

function scheduleAccessTokenRefresh() {
    const access = getCookie('access_token');
    const refresh = getCookie('refresh_token');
    if (!access || !refresh) return;
    const payload = parseJwt(access);
    if (!payload || !payload.exp) return;
    const now = Math.floor(Date.now() / 1000);
    const secondsLeft = payload.exp - now;
    const refreshIn = (secondsLeft - 30) * 1000;
    if (refreshIn <= 0) {
        doRefreshToken();
    } else {
        setTimeout(doRefreshToken, refreshIn);
    }
}

async function doRefreshToken() {
    const refresh = getCookie('refresh_token');
    if (!refresh) {
        try {
            const response = await fetch(window.location.pathname, {
                method: 'GET',
                credentials: 'include',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (response.ok) {
                return;
            }

            if (response.status === 302) {
                window.location.replace(window.LOGIN_URL);
                return;
            }
        } catch (e) {
            return;
        }

        return;
    }
    try {
        const resp = await fetch('/authentication/token/refresh/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include'
        });
        if (resp.ok) {
            scheduleAccessTokenRefresh();
        } else {
            try {
                const response = await fetch(window.location.pathname, {
                    method: 'GET',
                    credentials: 'include',
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });

                if (response.ok) {
                    return;
                }

                if (response.status === 302) {
                    window.location.replace(window.LOGIN_URL);
                    return;
                }
            } catch (e) {
                return;
            }
        }
    } catch (e) {
        setTimeout(doRefreshToken, 10000);
    }
}

async function refreshTokensIfNeeded() {
    const access = getCookie('access_token');
    const refresh = getCookie('refresh_token');

    if (!access || !refresh) {
        try {
            const response = await fetch('/authentication/token/session/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (response.ok) {
                return true;
            }
        } catch (e) {
        }
        return false;
    }

    const payload = parseJwt(access);
    if (!payload || !payload.exp) {
        try {
            const response = await fetch('/authentication/token/refresh/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (response.ok) {
                return true;
            }
        } catch (e) {
        }
        return false;
    }

    const now = Math.floor(Date.now() / 1000);
    const secondsLeft = payload.exp - now;

    if (secondsLeft <= 30) {
        try {
            const response = await fetch('/authentication/token/refresh/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include'
            });

            if (response.ok) {
                return true;
            }
        } catch (e) {
        }
        return false;
    }

    return true;
}

window.tokens = {
    ensureValidAccessToken,
    scheduleAccessTokenRefresh,
    doRefreshToken,
    parseJwt,
    refreshTokensIfNeeded
};
