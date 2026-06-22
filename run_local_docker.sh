#!/bin/bash

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

IMAGE_NAME="binance-data-mcp-server"
CONTAINER_NAME="binance-data-mcp-local"

echo -e "${BLUE}🚀 Starting binance-data MCP Server in Docker...${NC}"
echo

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo -e "${BLUE}📋 Copying .env.example to .env...${NC}"
        cp .env.example .env
    else
        echo -e "${RED}❌ Missing .env.example${NC}"
        exit 1
    fi
fi

set -a
source .env
set +a

HOST_PORT=${PORT:-8000}
CONTAINER_PORT=${PORT:-8000}

if ! command -v docker &> /dev/null; then
    echo -e "${RED}❌ Docker is not installed.${NC}"
    exit 1
fi

if [ -z "$SERVER_ADDRESS" ] || [ -z "$MCP_OPERATOR_PRIVATE_KEY" ] || [ -z "$MCP_OPERATOR_ADDRESS" ]; then
    echo -e "${RED}❌ Missing required wallet values in .env${NC}"
    echo -e "${YELLOW}   Set SERVER_ADDRESS, MCP_OPERATOR_PRIVATE_KEY, and MCP_OPERATOR_ADDRESS first.${NC}"
    exit 1
fi


if docker ps -a | grep -q $CONTAINER_NAME; then
    echo -e "${YELLOW}🛑 Removing existing container...${NC}"
    docker stop $CONTAINER_NAME >/dev/null 2>&1 || true
    docker rm $CONTAINER_NAME >/dev/null 2>&1 || true
fi

echo -e "${BLUE}🔨 Building Docker image...${NC}"
if [ -n "$TRAIA_IATP_LOCAL_SOURCE" ] && [ -d "$TRAIA_IATP_LOCAL_SOURCE" ]; then
    echo -e "${BLUE}📦 Using local IATP source: $TRAIA_IATP_LOCAL_SOURCE${NC}"
    mkdir -p .docker-iatp
    cp -R "$TRAIA_IATP_LOCAL_SOURCE" .docker-iatp/IATP
    docker build --no-cache -t $IMAGE_NAME .
    rm -rf .docker-iatp
else
    docker build --no-cache -t $IMAGE_NAME .
fi

echo -e "${BLUE}🏃 Starting container...${NC}"
docker run -d \
    --name $CONTAINER_NAME \
    -p $HOST_PORT:$CONTAINER_PORT \
    --env-file .env \
    $IMAGE_NAME

echo -e "${YELLOW}⏳ Waiting for server to start...${NC}"
sleep 3

if ! docker ps | grep -q $CONTAINER_NAME; then
    echo -e "${RED}❌ Container failed to start. Logs:${NC}"
    docker logs $CONTAINER_NAME
    exit 1
fi

echo
echo -e "${GREEN}✅ binance-data MCP Server is running${NC}"
echo -e "${BLUE}   MCP endpoint:${NC} ${GREEN}http://localhost:${HOST_PORT}/mcp${NC}"
echo -e "${BLUE}   Health check:${NC} ${GREEN}http://localhost:${HOST_PORT}/health${NC}"
echo
echo -e "${BLUE}📝 Useful commands:${NC}"
echo -e "   Logs:   ${YELLOW}docker logs -f ${CONTAINER_NAME}${NC}"
echo -e "   Stop:   ${YELLOW}docker stop ${CONTAINER_NAME}${NC}"
echo -e "   Shell:  ${YELLOW}docker exec -it ${CONTAINER_NAME} /bin/bash${NC}"
echo

if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${HOST_PORT}/health" | grep -q "200"; then
    echo -e "${GREEN}✅ Health check passed${NC}"
else
    echo -e "${YELLOW}⚠️  Health check has not passed yet. Check container logs.${NC}"
fi