# syntax=docker/dockerfile:1
# Build context: backend/ (repo backend root). CDK passes --build-arg AGENT=planner|tagger|...
ARG AGENT=planner

FROM public.ecr.aws/lambda/python:3.12

ARG AGENT

ENV LAMBDA_TASK_ROOT=/var/task

WORKDIR /work
RUN pip install --no-cache-dir "uv>=0.5"

COPY database /work/database
COPY ${AGENT} /work/agent

WORKDIR /work/agent
RUN uv export --no-hashes --no-emit-project -o /work/req.txt && \
    (grep -v '^pyperclip' /work/req.txt > /work/reqf.txt || cp /work/req.txt /work/reqf.txt)

RUN uv pip install --system --target "${LAMBDA_TASK_ROOT}" -r /work/reqf.txt

RUN cp /work/agent/*.py "${LAMBDA_TASK_ROOT}/"

COPY env_bootstrap.py ${LAMBDA_TASK_ROOT}/

WORKDIR ${LAMBDA_TASK_ROOT}
CMD ["lambda_handler.lambda_handler"]
