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

async function ensureValidAccessToken() {
    const access = localStorage.getItem('access_token');
    const refresh = localStorage.getItem('refresh_token');
    if (!access || !refresh) {
        window.location.replace('/users/login/');
        return false;
    }
    const payload = parseJwt(access);
    if (!payload || !payload.exp) {
        window.location.replace('/users/login/');
        return false;
    }
    const now = Math.floor(Date.now() / 1000);
    const secondsLeft = payload.exp - now;
    if (secondsLeft <= 30) {
        try {
            const resp = await fetch('/authentication/token/refresh/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh })
            });
            if (resp.ok) {
                const data = await resp.json();
                localStorage.setItem('access_token', data.access);
                if (data.refresh) {
                    localStorage.setItem('refresh_token', data.refresh);
                }
                return true;
            } else {
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                window.location.replace('/users/login/');
                return false;
            }
        } catch (e) {
            window.location.replace('/users/login/');
            return false;
        }
    }
    return true;
}

function scheduleAccessTokenRefresh() {
    const access = localStorage.getItem('access_token');
    const refresh = localStorage.getItem('refresh_token');
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
    const refresh = localStorage.getItem('refresh_token');
    if (!refresh) {
        window.location.replace('/users/login/');
        return;
    }
    try {
        const resp = await fetch('/authentication/token/refresh/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh })
        });
        if (resp.ok) {
            const data = await resp.json();
            localStorage.setItem('access_token', data.access);
            if (data.refresh) {
                localStorage.setItem('refresh_token', data.refresh);
            }
            scheduleAccessTokenRefresh();
        } else {
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            window.location.replace('/users/login/');
        }
    } catch (e) {
        setTimeout(doRefreshToken, 10000);
    }
}

window.tokens = {
    ensureValidAccessToken,
    scheduleAccessTokenRefresh,
    doRefreshToken,
    parseJwt
};
