const API_BASE_URL = 'http://localhost:8000';

let authToken: string | null = localStorage.getItem('access_token');

export const setAuthToken = (token: string | null) => {
    authToken = token;
    if (token) {
        localStorage.setItem('access_token', token);
    } else {
        localStorage.removeItem('access_token');
    }
};

export const getAuthToken = () => authToken;

async function apiRequest<T>(
    endpoint: string,
    options: RequestInit = {}
): Promise<T> {
    const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...options.headers,
    };

    if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
    }

    const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        ...options,
        headers,
    });

    if (response.status === 401) {
        setAuthToken(null);
        window.location.href = '/login';
        throw new Error('Unauthorized');
    }

    if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'API request failed');
    }

    return response.json();
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
    compile: (content: string) =>
        apiRequest<{ pdf_base64?: string; error_log?: string }>('/compile', {
            method: 'POST',
            body: JSON.stringify({ content }),
        }),
    fixErrors: (content: string, errors: string) =>
        apiRequest<{ fixed_code: string }>('/compile/fix-errors', {
            method: 'POST',
            body: JSON.stringify({ content, errors }),
        }),
};

// API для аутентификации
export const authAPI = {
    register: (email: string, username: string, password: string) =>
        apiRequest<{ access_token: string; user: any }>('/auth/register', {
            method: 'POST',
            body: JSON.stringify({ email, username, password }),
        }),

    login: (email: string, password: string) =>
        apiRequest<{ access_token: string; user: any }>('/auth/login', {
            method: 'POST',
            body: JSON.stringify({ email, password }),
        }),

    getCurrentUser: () =>
        apiRequest<{ id: string; email: string; username: string }>('/auth/me'),

    logout: () => {
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
    // Базовые методы
    get: (url: string) => apiRequest(url),
    post: (url: string, data: any) => apiRequest(url, { method: 'POST', body: JSON.stringify(data) }),
    put: (url: string, data: any) => apiRequest(url, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (url: string) => apiRequest(url, { method: 'DELETE' }),
    
    // Компиляция
    compileDocument: (content: string) => apiRequest('/compile', {
        method: 'POST',
        body: JSON.stringify({ content })
    }),
    fixErrors: (data: { content: string; error_log: string }) => apiRequest('/compile/fix-errors', {
        method: 'POST',
        body: JSON.stringify(data)
    }),
    
    // Документы
    getDocuments: () => apiRequest<any[]>('/documents'),
    getDocument: (id: string) => apiRequest<any>(`/documents/${id}`),
    createDocument: (data: { title: string; content: string }) => 
        apiRequest<any>('/documents', { method: 'POST', body: JSON.stringify(data) }),
    updateDocument: (id: string, data: { title: string; content: string }) => 
        apiRequest<any>(`/documents/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    deleteDocument: (id: string) => apiRequest<void>(`/documents/${id}`, { method: 'DELETE' }),
};