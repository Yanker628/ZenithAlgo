package handlers

import (
	"net/http"

	"github.com/zenithalgo/api/internal/models"
	"github.com/zenithalgo/api/internal/services"

	"github.com/gin-gonic/gin"
)

type JobHandler struct {
	service *services.JobService
}

func NewJobHandler(service *services.JobService) *JobHandler {
	return &JobHandler{service: service}
}

// SubmitBacktest 处理回测提交请求
func (h *JobHandler) SubmitBacktest(c *gin.Context) {
	var req models.JobRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}

	jobID, err := h.service.SubmitBacktest(c, req)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "Failed to submit job"})
		return
	}

	c.JSON(http.StatusAccepted, models.JobResponse{JobID: jobID})
}
