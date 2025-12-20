package models

type JobRequest struct {
	Config map[string]interface{} `json:"config" binding:"required"`
}

type JobResponse struct {
	JobID string `json:"job_id"`
}
