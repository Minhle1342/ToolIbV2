class startAPI {
    async getProjects() {
        const res = await fetch('/api/projects');
        return await res.json();
    }

    async createProject(data) {
        const res = await fetch('/api/projects', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async deleteProject(id) {
        const res = await fetch(`/api/projects/${id}`, { method: 'DELETE' });
        return await res.json();
    }

    async updateProject(id, data) {
        const res = await fetch(`/api/projects/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async scanProject(id) {
        const res = await fetch(`/api/projects/scan/${id}`, { method: 'POST' });
        return await res.json();
    }

    async createView(data) {
        const res = await fetch('/api/views', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async assignView(data) {
        const res = await fetch('/api/views/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return res.json();
    }

    async getImages(filters) {
        const params = new URLSearchParams(filters);
        const res = await fetch(`/api/images?${params}`);
        return await res.json();
    }

    async saveLabel(data) {
        const res = await fetch('/api/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return res.json();
    }

    async getLabel(imageId) {
        const res = await fetch(`/api/labels/${imageId}`);
        return await res.json();
    }

    async autoLabel(imageId) {
        const res = await fetch(`/api/autolabel/${imageId}`, {
            method: 'POST'
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Auto Labeling failed');
        }
        return await res.json();
    }

    async exportDataset(data) {
        const res = await fetch('/api/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async deleteImage(imageId) {
        const res = await fetch(`/api/images/${imageId}`, {
            method: 'DELETE'
        });
        return await res.json();
    }

    async getAssignStats(projectId) {
        const res = await fetch(`/api/projects/${projectId}/assign-stats`);
        return await res.json();
    }
}

const API = new startAPI();
