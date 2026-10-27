"""Owner-triggered verification: isolated adversarial suite, then real Discord probes."""

from __future__ import annotations
import asyncio
import io
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
import discord
from tier_ui import edit, payload, message_files, component_dicts
from community_domain import ROOT
from tier_image import image_file
from tier_store import TierStore
from tier_views import GuardedView, PollView, reply
from tier_release import build_info, label as build_label

SUITE_TIMEOUT = 480
HOST_TEST_PATTERNS = (
    "test_tier*.py",
    "test_global*.py",
    "test_banner*.py",
    "test_instance_storage.py",
    "test_runtime_health.py",
    "test_storage_maintenance.py",
)
PROGRESS_MARKER = "TIER_SUITE_PROGRESS "

# The subprocess has no production credentials, dotenv imports or external network.
BOOTSTRAP = """
import fnmatch,json,socket,unittest,sys
from pathlib import Path
import dotenv
dotenv.load_dotenv=lambda *a,**k:False
original_dns=socket.getaddrinfo
original_connect=socket.socket.connect
original_connect_ex=socket.socket.connect_ex
allowed=(None,'localhost','127.0.0.1','::1','0.0.0.0','::')
def dns(host,*a,**k):
    if host not in allowed: raise OSError('External network disabled during isolated verification')
    return original_dns(host,*a,**k)
def connect(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6) and address[0] not in allowed:
        raise OSError('External network disabled during isolated verification')
    return original_connect(self,address)
def connect_ex(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6) and address[0] not in allowed:
        raise OSError('External network disabled during isolated verification')
    return original_connect_ex(self,address)
socket.getaddrinfo=dns
socket.socket.connect=connect
socket.socket.connect_ex=connect_ex
files=sorted(p.name for p in Path('tests').glob('test_*.py'))
current=[f for f in files if any(fnmatch.fnmatchcase(f,p) for p in sys.argv[2:])]
groups=[current[index::3] for index in range(3)]
selected=groups[int(sys.argv[1])]
if not selected:
    print('Nenhum arquivo nesta parte.')
    raise SystemExit(0)
suite=unittest.TestSuite(unittest.defaultTestLoader.discover('tests',pattern=name) for name in selected)
class ProgressResult(unittest.TextTestResult):
    def stopTest(self,test):
        super().stopTest(test)
        print('\\nTIER_SUITE_PROGRESS '+json.dumps({
            'group':int(sys.argv[1]),'completed':self.testsRun,
            'failures':len(self.failures),'errors':len(self.errors),
            'last_test':test.id(),
            'failed_tests':[t.id() for t,_ in (self.failures+self.errors)][-10:],
        }),flush=True)
result=unittest.TextTestRunner(verbosity=1,resultclass=ProgressResult).run(suite)
raise SystemExit(not result.wasSuccessful())
"""


def suite_progress(output):
    groups = {}
    for line in output.splitlines():
        if line.startswith(PROGRESS_MARKER):
            row = json.loads(line[len(PROGRESS_MARKER) :])
            groups[row["group"]] = row
    return {
        "completed": sum(row["completed"] for row in groups.values())
        if groups
        else sum(int(n) for n in re.findall(r"Ran (\d+) tests?\b", output)),
        "failures": sum(row["failures"] for row in groups.values()),
        "errors": sum(row["errors"] for row in groups.values()),
        "groups": list(groups.values()),
    }


def suite_output(output):
    """Keep the last progress record without crowding failure tracebacks out."""
    lines, progress = [], ""
    for line in output.decode(errors="replace").splitlines():
        if line.startswith(PROGRESS_MARKER):
            progress = line
        else:
            lines.append(line)
    return "\n".join(lines)[-65000:] + "\n" + progress


class SuiteTimeout(TimeoutError):
    def __init__(self, output):
        super().__init__("Isolated verification reached its time budget")
        self.output = output
        self.progress = suite_progress(output)


async def isolated_suite():
    environment = {
        k: v
        for k, v in os.environ.items()
        if k in {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "LD_LIBRARY_PATH"}
    }
    with tempfile.TemporaryDirectory(prefix="tier-verification-") as directory:
        environment["DATA_DIR"] = directory
        environment["HOME"] = directory
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        # Hosts may install with --prefix=.local and expose packages through
        # user-site/PYTHONPATH. Changing HOME must not hide the loaded runtime.
        # Rebuild the import path from trusted parent paths, never inherit secrets.
        paths = []
        for entry in sys.path:
            path = Path(entry or ROOT).resolve()
            if path.is_dir() or (path.is_file() and path.suffix in (".zip", ".egg")):
                if str(path) not in paths:
                    paths.append(str(path))
        environment["PYTHONPATH"] = os.pathsep.join(paths)
        chunks = []
        succeeded = True
        deadline = asyncio.get_running_loop().time() + SUITE_TIMEOUT
        # Sequential processes release Pillow/legacy caches between groups, keeping
        # the verification alongside the live bot within the small hosting budget.
        for group in range(3):
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                BOOTSTRAP,
                str(group),
                *HOST_TEST_PATTERNS,
                cwd=ROOT,
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            communication = asyncio.create_task(process.communicate())
            try:
                output, _ = await asyncio.wait_for(
                    asyncio.shield(communication),
                    timeout=max(0.1, deadline - asyncio.get_running_loop().time()),
                )
            except (TimeoutError, asyncio.CancelledError) as error:
                if process.returncode is None:
                    process.kill()
                output, _ = await communication
                if isinstance(error, TimeoutError):
                    chunks.append(f"Parte {group + 1}/3\n" + suite_output(output))
                    raise SuiteTimeout("\n".join(chunks)) from None
                raise
            succeeded = succeeded and process.returncode == 0
            chunks.append(f"Parte {group + 1}/3\n" + suite_output(output))
    text = "\n".join(chunks)
    count = suite_progress(text)["completed"]
    return succeeded and count > 0, count, text


class VerificationClick(GuardedView):
    def __init__(self, bot, owner, guild, report, origin):
        super().__init__(timeout=600)
        self.bot, self.owner, self.guild, self.report, self.origin = (
            bot,
            owner,
            guild,
            report,
            origin,
        )

    async def interaction_check(self, i):
        if (
            i.user.id != self.owner
            or i.guild_id != self.guild
            or not self.bot.is_owner_id(i.user.id)
        ):
            await reply(i, "Esta verificação é privada do responsável pelo bot.")
            return False
        return True

    @discord.ui.button(
        label="Confirmar teste de interação", style=discord.ButtonStyle.primary
    )
    async def click(self, i, button):
        if not await self.interaction_check(i):
            return
        # Exercise the exact production vote callback against an isolated database.
        with tempfile.TemporaryDirectory(prefix="tier-click-") as directory:
            store = TierStore(Path(directory) / "tierlist.sqlite3")
            try:
                store.create_proposal(
                    [{"unit_id": "daki", "tier": "GOOD_GROUND"}],
                    {},
                    details={
                        "daki": {
                            "tier": "GOOD_GROUND",
                            "before": None,
                            "reason": "Dados artificiais exclusivos da verificação, sem avaliação real.",
                            "sources": [],
                        }
                    },
                    source_version="verification-only",
                    model="verification-only",
                    comments=[],
                )
                proposal = store.active_proposal()
                store.remember_poll(
                    proposal["id"], i.guild_id, i.channel_id, i.message.id
                )
                adapter = SimpleNamespace(
                    store=store, require_human=self.bot.require_human
                )
                await PollView(adapter).cast(i, "approve")
                if store.poll_counts(proposal["id"]) != {
                    "approve": 1,
                    "keep": 0,
                    "test": 0,
                }:
                    raise ValueError("A interação não produziu o registro esperado.")
            finally:
                store.close()
        self.report["checks"] = [
            row
            for row in self.report["checks"]
            if row["name"] != "Clique humano entregue ao callback de voto"
        ]
        self.report["checks"].append(
            {
                "name": "Clique humano entregue ao callback de voto",
                "result": "passed",
                "level": "Discord real + banco isolado",
            }
        )
        self.bot.store.set("last_verified_click", time.time())
        button.disabled = True
        await edit(
            i,
            content="**Interação confirmada.** O Discord entregou seu clique ao mesmo código que registra votos. O registro foi feito num banco temporário; nenhuma posição ou voto global foi alterado.",
        )
        self.bot.store.set(
            "last_verification_report", json.dumps(self.report, ensure_ascii=False)
        )
        file = discord.File(
            io.BytesIO(
                (json.dumps(self.report, indent=2, ensure_ascii=False) + "\n").encode()
            ),
            filename="verificacao-tierlist.json",
        )
        try:
            await edit(
                self.origin, content=summary(self.report), attachments=[file], view=self
            )
        finally:
            file.close()

    @discord.ui.button(label="Ver alterações de personagens")
    async def visual(self, i, button):
        if not await self.interaction_check(i):
            return
        from tier_preview import open_demo

        await open_demo(self.bot, i)


def summary(report):
    lines = ["## Verificação da tier list"]
    if report.get("build"):
        lines.append("**Versão em execução:** " + build_label(report["build"]))
    labels = {
        "passed": "Passou",
        "failed": "Falhou",
        "warning": "Atenção",
        "not-tested": "Não testado",
    }
    for row in report["checks"]:
        lines.append(
            f"**{labels[row['result']]}** · {row['name']}"
            + (f" — {row['detail']}" if row.get("detail") else "")
        )
    lines += [
        "\nOs testes de disputa usam dados artificiais em bancos temporários. O teste real envia mensagens técnicas em um tópico separado e tenta limpar os próprios artefatos.",
        "Celular/computador, permissões de cada participante e carga de servidores reais continuam sujeitos à validação de uso. O resultado descreve o que foi executado, sem prometer ausência total de erros.",
    ]
    return "\n".join(lines)[:1950]


def discord_failure(error, stage):
    row = {
        "name": "Fluxo real do Discord",
        "result": "failed",
        "stage": stage,
        "level": "Discord real",
    }
    if isinstance(error, discord.HTTPException):
        row.update(http_status=error.status, discord_code=error.code)
        if error.status == 403:
            hint = "Confira as permissões do bot neste canal e tópico."
        elif error.status == 404:
            hint = "A mensagem ou o tópico ficou indisponível durante o teste."
        elif error.status == 400:
            hint = "O Discord recusou o formato enviado; encaminhe este JSON ao responsável pelo código."
        else:
            hint = "Não foi possível concluir a chamada; tente novamente em instantes."
        # Do not serialize the response body: it can echo message text, CDN URLs
        # or uploads. The stage and numeric API codes identify the failure safely.
        row["detail"] = f"{stage}: HTTP {error.status}, código {error.code}. {hint}"
    else:
        detail = str(error) if isinstance(error, ValueError) else type(error).__name__
        row["detail"] = f"{stage}: {detail}"
    return row


async def verify(bot, i):
    bot.require_owner(i)
    task = asyncio.current_task()
    bot.verification_tasks.add(task)
    try:
        return await _verify(bot, i)
    finally:
        bot.verification_tasks.discard(task)


async def _verify(bot, i):
    bot.require_owner(i)
    if bot.verification_lock.locked():
        raise ValueError("Já existe uma verificação em andamento.")
    if time.time() - float(bot.store.get("last_verification") or 0) < 300:
        raise ValueError("Aguarde cinco minutos entre verificações completas.")
    async with bot.verification_lock:
        bot.store.set("last_verification", time.time())
        report = {
            "schema": 1,
            "started_at": time.time(),
            "checks": [],
            "writes_production_ranking": False,
            "ranking_before": bot.store.board()["id"],
            "isolated_scope": {
                "profile": "tierlist-and-shared-runtime",
                "patterns": list(HOST_TEST_PATTERNS),
                "timeout_seconds": SUITE_TIMEOUT,
                "includes_archived_features": False,
            },
        }
        installed = build_info()
        running = getattr(bot, "build", installed)
        report["build"] = running
        report["installed_build"] = installed
        healthy_build = (
            installed["verified"]
            and running["verified"]
            and installed.get("fingerprint") == running.get("fingerprint")
            and installed["version"] == running["version"]
        )
        report["checks"].append(
            {
                "name": "Versão e integridade dos arquivos",
                "result": "passed" if healthy_build else "failed",
                "level": "hospedagem",
                "detail": f"{build_label(installed)} · {installed['files_checked']} arquivos conferidos."
                if healthy_build
                else f"Em execução: {build_label(running)}; instalado: {build_label(installed)}. Atualize o conjunto completo de arquivos e reinicie; o pacote ou a versão carregada diverge.",
            }
        )

        async def progress(text):
            await edit(i, content="### Verificação em andamento\n" + text, view=None)

        await progress(
            "Executando os testes da tier list e dos recursos compartilhados em bancos isolados, com até oito minutos. Os módulos antigos são testados no GitHub. Depois seguem os testes reais do Discord."
        )
        try:
            passed, count, output = await isolated_suite()
            report["isolated_progress"] = suite_progress(output)
            report["checks"].append(
                {
                    "name": f"Cenários da tier list: {count} testes",
                    "result": "passed" if passed else "failed",
                    "level": "isolated",
                    **(
                        {
                            "detail": "A suíte não iniciou. O relatório contém o erro de carregamento."
                        }
                        if not passed and count == 0
                        else {}
                    ),
                }
            )
            if not passed:
                report["isolated_output"] = output[-40000:]
        except SuiteTimeout as error:
            state = error.progress
            report["isolated_progress"] = state
            report["isolated_output"] = error.output[-40000:]
            report["checks"].append(
                {
                    "name": f"Cenários da tier list: {state['completed']} testes concluídos",
                    "result": "failed"
                    if state["failures"] or state["errors"]
                    else "warning",
                    "level": "isolated",
                    "detail": "Suíte incompleta: atingiu o limite de oito minutos da verificação. O JSON conserva o progresso e as falhas encontradas; as etapas reais seguem abaixo.",
                }
            )
        except (TimeoutError, OSError) as error:
            report["checks"].append(
                {
                    "name": "Cenários da tier list",
                    "result": "warning",
                    "level": "isolated",
                    "detail": "A hospedagem não conseguiu concluir a execução isolada. Confira os arquivos e recursos disponíveis; as etapas reais seguem abaixo.",
                    "error_type": type(error).__name__,
                }
            )
        await progress(
            "Conferindo a conexão real da IA, com o orçamento gratuito respeitado."
        )
        async with bot.analysis_lock:
            success = float(bot.store.get("last_connection_success") or 0)
            if 0 <= bot.store.clock() - success < 300:
                response = "Conexão confirmada por uma resposta válida nos últimos cinco minutos; sem nova chamada."
            else:
                response = await bot.analyzer.check_connection()
        report["checks"].append(
            {
                "name": "Resposta real da IA",
                "result": "passed"
                if "confirmada por uma resposta válida" in response
                else "warning",
                "detail": response,
                "level": "Groq real",
            }
        )
        await progress(
            "Testando publicação, leitura, edição, botões e arquivamento em um tópico técnico temporário."
        )
        thread = None
        messages = []
        channel = (
            i.channel.parent if isinstance(i.channel, discord.Thread) else i.channel
        )
        stage = "Registro real dos comandos"
        try:
            if not isinstance(channel, discord.TextChannel):
                raise ValueError("Use a verificação a partir de um canal de texto.")
            remote = await bot.tree.fetch_commands()
            if {c.name for c in remote} != {c.name for c in bot.tree.get_commands()} or any(
                c.options for c in remote
            ):
                raise ValueError(
                    "Os comandos registrados no Discord não correspondem à configuração atual do bot."
                )
            for command in remote:
                permissions = command.default_member_permissions
                if command.name in {"tierlist", "setbanner", "dailychallenge"} and (
                    permissions is None
                    or permissions.value != discord.Permissions(manage_guild=True).value
                ):
                    raise ValueError(
                        f"A permissão padrão de /{command.name} no Discord precisa ser Gerenciar servidor. Atualize e reinicie o bot para sincronizar os comandos."
                    )
                if (
                    command.name == "globalchat"
                    and permissions is not None
                    and permissions.value
                ):
                    raise ValueError(
                        "O /globalchat precisa estar disponível aos membros para abrir os controles pessoais privados. Atualize e reinicie o bot; a configuração continua protegida por Gerenciar servidor."
                    )
            report["checks"].append(
                {
                    "name": "Registro real dos comandos",
                    "result": "passed",
                    "level": "Discord real",
                    "detail": "/tierlist e /setbanner restritos a Gerenciar servidor; /globalchat abre controles pessoais privados para membros e mantém configuração protegida para ADMs.",
                }
            )
            stage = "Criação real de tópico privado"
            private = bool(
                getattr(
                    channel.permissions_for(channel.guild.me),
                    "create_private_threads",
                    False,
                )
            )
            if not private:
                raise ValueError(
                    "Para verificar publicações sem expor testes aos membros, conceda Criar tópicos privados ao bot neste canal. A demonstração visual privada continua disponível."
                )
            thread = await channel.create_thread(
                name="Verificação técnica · temporária",
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=60,
                reason="Verificação solicitada pelo responsável pelo bot",
            )
            await thread.add_user(i.user)
            report["checks"].append(
                {
                    "name": "Criação real de tópico",
                    "result": "passed",
                    "level": "Discord real",
                    "detail": "Tópico privado, com convite ao responsável.",
                }
            )
            stage = "Envio e leitura real da imagem"
            blob, _ = await bot.picture()
            file = image_file(blob)
            try:
                message = await thread.send(
                    **payload(
                        bot=bot,
                        content="**Teste técnico.** Esta imagem é uma cópia de verificação; nenhuma posição será alterada.",
                        file=file,
                    ),
                )
            finally:
                file.close()
            messages.append(message)
            fetched = await thread.fetch_message(message.id)
            if len(message_files(fetched)) != 1:
                raise ValueError("O Discord não devolveu a imagem esperada.")
            report["checks"].append(
                {
                    "name": "Envio e leitura real da imagem",
                    "result": "passed",
                    "level": "Discord real",
                }
            )
            stage = "Edição real da mesma imagem"
            file = image_file(blob)
            try:
                await message.edit(
                    **payload(
                        bot=bot,
                        content="**Teste técnico.** Edição da mesma mensagem confirmada.",
                        attachments=[file],
                    )
                )
            finally:
                file.close()
            fetched = await thread.fetch_message(message.id)
            if fetched.id != message.id or not message_files(fetched):
                raise ValueError("A edição não foi confirmada.")
            report["checks"].append(
                {
                    "name": "Edição real da mesma imagem",
                    "result": "passed",
                    "level": "Discord real",
                }
            )
            from tier_preview import check_visual_sequence, check_portrait_sequence

            stage = "Personagens, ordem, tiers e substituição de retratos"
            report["visual_steps"] = await check_visual_sequence(bot, message)
            report["checks"].append(
                {
                    "name": "Personagens, ordem, tiers e substituição de retratos: 10 etapas",
                    "result": "passed",
                    "level": "Discord real + dados isolados",
                }
            )
            stage = "Lista de retratos: envio, aprovação, rejeição e restauração"
            report["portrait_steps"] = await check_portrait_sequence(bot, message)
            report["checks"].append(
                {
                    "name": "Lista de retratos: envio, aprovação, rejeição e restauração",
                    "result": "passed",
                    "level": "Discord real + dados isolados",
                    "detail": "Cinco etapas, incluindo remover e recolocar o TXT na mesma mensagem.",
                }
            )
            stage = "Publicação e edição real de botões"
            view = PollView(bot, closed=True)
            for item in view.children:
                item.disabled = True
            card = await thread.send(
                **payload(
                    bot=bot,
                    embed=discord.Embed(
                        title="Verificação de componentes",
                        description="Botões de teste desativados. Esta mensagem não é uma proposta.",
                    ),
                    view=view,
                )
            )
            messages.append(card)
            fetched = await thread.fetch_message(card.id)
            if sum(item.get("type") == 2 for item in component_dicts(fetched)) != 4:
                raise ValueError("Os componentes não foram confirmados pelo Discord.")
            await card.edit(
                **payload(
                    bot=bot,
                    content="Componentes recebidos e removidos com sucesso.",
                    view=None,
                )
            )
            report["checks"].append(
                {
                    "name": "Publicação e edição real de botões",
                    "result": "passed",
                    "level": "Discord real",
                }
            )
            stage = "Arquivamento e retomada reais"
            await thread.edit(archived=True)
            fetched = await bot.fetch_channel(thread.id)
            if not fetched.archived:
                raise ValueError("Arquivamento não confirmado.")
            await fetched.edit(archived=False)
            resumed = await fetched.send(
                **payload(
                    bot=bot,
                    content="Retomada do tópico confirmada. Encerrando a verificação.",
                )
            )
            messages.append(resumed)
            thread = fetched
            report["checks"].append(
                {
                    "name": "Arquivamento e retomada reais",
                    "result": "passed",
                    "level": "Discord real",
                }
            )
        except (discord.HTTPException, ValueError, OSError, TimeoutError) as error:
            report["checks"].append(discord_failure(error, stage))
        finally:
            cleanup = True
            for message in reversed(messages):
                try:
                    await message.delete()
                except discord.NotFound:
                    pass
                except discord.HTTPException:
                    cleanup = False
            if thread:
                try:
                    other_messages = False
                    async for message in thread.history(limit=30):
                        if not bot.user or message.author.id != bot.user.id:
                            other_messages = True
                    if (
                        channel.permissions_for(channel.guild.me).manage_threads
                        and not other_messages
                    ):
                        await thread.delete(
                            reason="Verificação concluída; somente artefatos técnicos"
                        )
                    else:
                        await thread.edit(archived=True)
                except discord.HTTPException:
                    cleanup = False
                report["checks"].append(
                    {
                        "name": "Limpeza dos artefatos técnicos",
                        "result": "passed" if cleanup else "warning",
                        "detail": "Sem Gerenciar tópicos, o tópico técnico vazio permanece arquivado.",
                        "level": "Discord real",
                    }
                )
        report["finished_at"] = time.time()
        report["ranking_after"] = bot.store.board()["id"]
        report["checks"] += [
            {
                "name": "Clique humano entregue ao callback de voto",
                "result": "not-tested",
                "detail": "Use Confirmar teste de interação abaixo.",
                "level": "Discord real + banco isolado",
            },
            {
                "name": "Aparência e seleção de arquivo no seu aplicativo",
                "result": "not-tested",
                "detail": "A API não reproduz a tela do celular/computador nem seleciona anexos por uma conta humana.",
                "level": "cliente Discord",
            },
        ]
        bot.store.set(
            "last_verification_report", json.dumps(report, ensure_ascii=False)
        )
        file = discord.File(
            io.BytesIO(
                (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode()
            ),
            filename="verificacao-tierlist.json",
        )
        try:
            await edit(
                i,
                content=summary(report),
                attachments=[file],
                view=VerificationClick(bot, i.user.id, i.guild_id, report, i),
            )
        finally:
            file.close()
        return report
