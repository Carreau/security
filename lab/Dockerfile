FROM python:3.12-slim

ARG SECURITY_OVERVIEW_REF=7131770f0789a0a6a6f69cd0dc0e5bc86a412765

RUN pip install --no-cache-dir \
      jupyterlab==4.6.3 \
      pandas==3.0.5 \
      matplotlib==3.11.1 \
      "security-overview @ https://github.com/Yann-P/github-security-overview/archive/${SECURITY_OVERVIEW_REF}.tar.gz"

RUN useradd --create-home --uid 1000 lab
USER lab
WORKDIR /home/lab/work

COPY --chown=lab:lab advisories.ipynb .

EXPOSE 8888
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--no-browser", "--ServerApp.root_dir=/home/lab/work"]
