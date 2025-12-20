FROM golang:1.21-alpine AS builder

WORKDIR /app

# 安装基础工具
RUN apk add --no-cache git

# 复制依赖定义
COPY go.mod go.sum ./
RUN go mod download

# 复制源码
COPY . .

# 构建
RUN go build -o api-server ./cmd/server/main.go

# 运行阶段
FROM alpine:latest

WORKDIR /root/

COPY --from=builder /app/api-server .

EXPOSE 8080

CMD ["./api-server"]
