const API_BASE_URL = 'http://localhost:8000';

export const setAuthToken = (token: string | null) => {
    console.log('setAuthToken called with:', token ? 'token present' : 'null');
    if (token) {
        localStorage.setItem('access_token', token);
        console.log('Token saved to localStorage');
    } else {
        localStorage.removeItem('access_token');
        console.log('Token removed from localStorage');
    }
};

export const getAuthToken = () => {
    const token = localStorage.getItem('access_token');
    console.log('getAuthToken returning:', token ? 'token present' : 'null');
    return token;
};

async function apiRequest<T>(
    endpoint: string,
    options: RequestInit = {}
): Promise<T> {
    console.log(`API Request: ${options.method || 'GET'} ${endpoint}`);
    
    const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...options.headers,
    };

    const token = getAuthToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
        console.log('Authorization header added');
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        ...options,
        headers,
    });

    console.log(`Response status: ${response.status}`);

    if (response.status === 401) {
        console.log('Unauthorized, clearing token');
        setAuthToken(null);
        if (!window.location.pathname.includes('/login')) {
            window.location.href = '/login';
        }
        throw new Error('Unauthorized');
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'API request failed');
    }

    const data = await response.json();
    console.log('Response data received');
    return data;
}

// API для документов
export const documentsAPI = {
    getAll: () => apiRequest<any[]>('/documents'),
    get: (id: string) => apiRequest<any>(`/documents/${id}`),
    create: (title: string, content: string) =>
        apiRequest<any>('/documents', {
            method: 'POST',
            body: JSON.stringify({ title, content }),
        }),
    update: (id: string, title: string, content: string) =>
        apiRequest<any>(`/documents/${id}`, {
            method: 'PUT',
            body: JSON.stringify({ title, content }),
        }),
    delete: (id: string) =>
        apiRequest<void>(`/documents/${id}`, { method: 'DELETE' }),
    compile: (content: string, compiler: string = 'pdflatex') =>
        apiRequest<{ pdf_base64?: string; error_log?: string }>('/compile', {
            method: 'POST',
            body: JSON.stringify({ content, compiler }),
        }),
    fixErrors: (code: string, errors: string) =>
        apiRequest<{ code: string }>('/ai/fix-errors', {
            method: 'POST',
            body: JSON.stringify({ code, errors }),
        }),
};

// API для аутентификации
export const authAPI = {
    register: (email: string, username: string, password: string) => {
        console.log('Register called with:', email, username);
        return apiRequest<{ access_token: string; user: any }>('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ email, username, password }),
        }).then(result => {
            console.log('Register response:', result);
            if (result.access_token) {
                setAuthToken(result.access_token);
            }
            return result;
        });
    },

    login: (email: string, password: string) => {
        console.log('Login called with:', email);
        return apiRequest<{ access_token: string; user: any }>('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password }),
        }).then(result => {
            console.log('Login response received');
            console.log('Has access_token?', !!result.access_token);
            if (result.access_token) {
                setAuthToken(result.access_token);
                console.log('Token should be saved now');
            } else {
                console.error('No access_token in response!');
            }
            return result;
        }).catch(err => {
            console.error('Login error:', err);
            throw err;
        });
    },

    getCurrentUser: () =>
        apiRequest<{ id: string; email: string; username: string }>('/auth/me'),

    logout: () => {
        console.log('Logout called');
        setAuthToken(null);
        window.location.href = '/login';
    },
};

// API для AI
export const aiAPI = {
    generate: (prompt: string) =>
        apiRequest<{ code: string }>('/ai/generate', {
            method: 'POST',
            body: JSON.stringify({ prompt }),
        }),
    explain: (code: string) =>
        apiRequest<{ explanation: string }>('/ai/explain', {
            method: 'POST',
            body: JSON.stringify({ code }),
        }),
};

// Совместимость с существующими компонентами
export const apiService = {
    get: (url: string) => apiRequest(url),
    post: (url: string, data: any) => apiRequest(url, { method: 'POST', body: JSON.stringify(data) }),
    put: (url: string, data: any) => apiRequest(url, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (url: string) => apiRequest(url, { method: 'DELETE' }),
    compileDocument: (content: string, compiler: string = 'pdflatex') => 
        apiRequest('/compile', {
            method: 'POST',
            body: JSON.stringify({ content, compiler })
        }),
    fixErrors: (data: { code: string; errors: string }) => apiRequest('/ai/fix-errors', {
        method: 'POST',
        body: JSON.stringify(data)
    }),
    getDocuments: () => apiRequest<any[]>('/documents'),
    getDocument: (id: string) => apiRequest<any>(`/documents/${id}`),
    createDocument: (data: { title: string; content: string }) =>
        apiRequest<any>('/documents', { method: 'POST', body: JSON.stringify(data) }),
    updateDocument: (id: string, data: { title: string; content: string }) =>
        apiRequest<any>(`/documents/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    deleteDocument: (id: string) => apiRequest<void>(`/documents/${id}`, { method: 'DELETE' }),

    // AI функции (внутри объекта apiService)
    generateLatex: (prompt: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ code: string }>('/ai/generate', {
            method: 'POST',
            body: JSON.stringify({ description: prompt, model })
        }),
    explainLatex: (code: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ text: string }>('/ai/explain', {
            method: 'POST',
            body: JSON.stringify({ code, model })
        }),
    deriveEquation: (expression: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ steps: string[]; final_result: string }>('/ai/derive-equation', {
            method: 'POST',
            body: JSON.stringify({ expression, model })
        }),
    checkUnits: (expression: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ consistent: boolean; details: string }>('/ai/check-units', {
            method: 'POST',
            body: JSON.stringify({ expression, model })
        }),
    verifyEquation: (lhs: string, rhs: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ equivalent: boolean; simplified_lhs: string; simplified_rhs: string }>('/ai/verify-equation', {
            method: 'POST',
            body: JSON.stringify({ lhs, rhs, model })
        }),
    generateTable: (data: { csv: string; has_header: boolean; use_booktabs: boolean }, model: string = 'gemma4-e4b') =>
        apiRequest<{ latex: string }>('/ai/generate-table', {
            method: 'POST',
            body: JSON.stringify({ ...data, model })
        }),
    generateDiagram: (data: { prompt: string; strict_latex_only: boolean }, model: string = 'gemma4-e4b') =>
        apiRequest<{ latex: string }>('/ai/generate-diagram', {
            method: 'POST',
            body: JSON.stringify({ ...data, model })
        }),
    fetchBibtex: (identifier: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ bibtex: string }>('/ai/fetch-bibtex', {
            method: 'POST',
            body: JSON.stringify({ identifier, model })
        }),
    addAltText: (figure_code: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ alt_text: string }>('/ai/add-alt-text', {
            method: 'POST',
            body: JSON.stringify({ figure_code, model })
        }),
    checkColor: (colors: string[], palette_type: string = 'all', model: string = 'gemma4-e4b') =>
        apiRequest<{ compliant: boolean; issues: string[] }>('/ai/check-color', {
            method: 'POST',
            body: JSON.stringify({ colors, palette_type, model })
        }),
    checkTemplate: (latex_code: string, template: string = 'ieee', model: string = 'gemma4-e4b') =>
        apiRequest<{ compliant: boolean; issues: string[] }>('/ai/check-template', {
            method: 'POST',
            body: JSON.stringify({ latex_code, template, model })
        }),
    getDiff: (old_text: string, new_text: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ diff: string }>('/ai/get-diff', {
            method: 'POST',
            body: JSON.stringify({ old_text, new_text, model })
        }),
    summarizeChanges: (old_text: string, new_text: string, model: string = 'gemma4-e4b') =>
        apiRequest<{ summary: string }>('/ai/summarize-changes', {
            method: 'POST',
            body: JSON.stringify({ old_text, new_text, model })
        }),
};