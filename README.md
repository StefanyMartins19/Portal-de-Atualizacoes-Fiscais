# Painel Fiscal AI (Protótipo Visual)

Sistema web em **Python + Flask** para centralizar atualizações fiscais coletadas automaticamente por palavras-chave.

## Funcionalidades

- Cadastro e remoção de palavras-chave fiscais.
- Coleta automática de notícias por RSS.
- Classificação de relevância por IA leve (matching semântico/lexical por palavras-chave).
- Gestão de status das notícias: **ativo** ou **descontinuado**.
- Dashboard visual com métricas.

## Executar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Acesse: `http://localhost:5000`

## Próximos passos sugeridos

- Trocar o classificador leve por embeddings/LLM.
- Adicionar autenticação por usuário.
- Criar API REST para integração com ERP/contabilidade.
- Adicionar trilha de auditoria para alterações de status.
