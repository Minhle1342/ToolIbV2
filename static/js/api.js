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

    async deleteProject(id, options = {}) {
        const res = await fetch(`/api/projects/${id}`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(options)
        });
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

    async getProjectGuide(id) {
        const res = await fetch(`/api/projects/${id}/guide`);
        return await res.json();
    }

    async uploadProjectGuide(id, formData) {
        const res = await fetch(`/api/projects/${id}/guide`, {
            method: 'POST',
            body: formData
        });
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

    async autoLabel(imageId, region = null) {
        const body = region ? JSON.stringify({ region }) : null;
        const headers = region ? { 'Content-Type': 'application/json' } : {};
        const res = await fetch(`/api/autolabel/${imageId}`, {
            method: 'POST',
            headers: headers,
            body: body
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

    async collectCrop(data) {
        const res = await fetch('/api/collect-crop', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async collectCropBatch(data) {
        const res = await fetch('/api/collect-crop/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async startCollectProjectCrops(projectId, data = {}) {
        const res = await fetch(`/api/projects/${projectId}/collect-crops/jobs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async getCollectCropsJob(jobId) {
        const res = await fetch(`/api/collect-crops/jobs/${jobId}`);
        return await res.json();
    }

    async getCollectStats() {
        const res = await fetch('/api/collect-crops/stats');
        return await res.json();
    }

    async deleteCollectedClass(className) {
        const res = await fetch(`/api/collect-crops/${encodeURIComponent(className)}`, {
            method: 'DELETE'
        });
        return await res.json();
    }

    async getCollectedPreview(className) {
        const res = await fetch(`/api/collect-crops/preview/${encodeURIComponent(className)}`);
        return await res.json();
    }

    async classifyBoxes(data) {
        const res = await fetch('/api/classify-boxes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async batchReview(data) {
        const res = await fetch('/api/images/batch-review', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }

    async batchDeleteImages(data) {
        const res = await fetch('/api/images/batch-delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return await res.json();
    }
    async mergeProjectsPreflight(data) {
        const res = await fetch('/api/projects/merge/preflight', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Preflight failed');
        }
        return await res.json();
    }

    async mergeProjects(data) {
        const res = await fetch('/api/projects/merge', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.error || 'Merge execution failed');
        }
        return await res.json();
    }
}

const API = new startAPI();
