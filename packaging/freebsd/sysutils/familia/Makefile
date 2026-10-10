# PRELIMINARY port of familia. Untested on FreeBSD (TBD): see README.md here.
PORTNAME=	familia
DISTVERSION=	0.0.20261009
CATEGORIES=	sysutils

MAINTAINER=	brianreborn@users.noreply.github.com
COMMENT=	Topology coordinator for a fleet of local LLM runtimes
WWW=		https://github.com/brianreborn/familia

LICENSE=	UNKNOWN
LICENSE_NAME=	familia license (see LICENSE)
LICENSE_FILE=	${WRKSRC}/LICENSE
LICENSE_PERMS=	dist-mirror dist-sell pkg-mirror pkg-sell auto-accept

RUN_DEPENDS=	${PYTHON_PKGNAMEPREFIX}pyyaml>0:devel/py-pyyaml@${PY_FLAVOR} \
		bash:shells/bash \
		git:devel/git \
		rsync:net/rsync \
		curl:ftp/curl

USES=		python:run shebangfix
USE_GITHUB=	yes
GH_ACCOUNT=	brianreborn
# TBD: pin to a tag/commit once fix/config-graph merges to main.
GH_TAGNAME=	fix/config-graph
USE_RC_SUBR=	familia_server

SHEBANG_FILES=	*.sh scripts/*.sh scripts/*.py
bash_CMD=	${LOCALBASE}/bin/bash

NO_BUILD=	yes
NO_ARCH=	yes

OPTIONS_DEFINE=		BITTORRENT DOCS EXAMPLES LLAMA VULKAN
OPTIONS_DEFAULT=	LLAMA
BITTORRENT_DESC=	BitTorrent transport via aria2
LLAMA_DESC=		Install llama.cpp runtime (misc/llama-cpp)
VULKAN_DESC=		Vulkan GPU support (set VULKAN on misc/ggml)

BITTORRENT_RUN_DEPENDS=	aria2c:www/aria2
LLAMA_RUN_DEPENDS=	llama-server:misc/llama-cpp
VULKAN_IMPLIES=		LLAMA
VULKAN_RUN_DEPENDS=	${LOCALBASE}/lib/libvulkan.so:graphics/vulkan-loader

LIBEXEC_TOP=	android_multi_start.sh android_start.sh install.sh \
		start-green-roomz.sh start.sh watchdog_android.sh with-fleet.sh
WRAPPERS=	familia-start familia-configure familia-validate familia-panel

do-install:
	@${MKDIR} ${STAGEDIR}${PREFIX}/libexec/familia/scripts
	${INSTALL_DATA} ${WRKSRC}/graph.yaml ${WRKSRC}/pins.txt \
		${STAGEDIR}${PREFIX}/libexec/familia
.for f in ${LIBEXEC_TOP}
	${INSTALL_SCRIPT} ${WRKSRC}/${f} ${STAGEDIR}${PREFIX}/libexec/familia
.endfor
	${INSTALL_SCRIPT} ${WRKSRC}/scripts/*.sh ${WRKSRC}/scripts/*.py \
		${STAGEDIR}${PREFIX}/libexec/familia/scripts
	${INSTALL_DATA} ${WRKSRC}/scripts/*.json \
		${STAGEDIR}${PREFIX}/libexec/familia/scripts
.for w in ${WRAPPERS}
	${SED} -e 's|%%PREFIX%%|${PREFIX}|g' ${FILESDIR}/${w}.in \
		> ${STAGEDIR}${PREFIX}/bin/${w}
	${CHMOD} 0755 ${STAGEDIR}${PREFIX}/bin/${w}
.endfor

do-install-DOCS-on:
	@${MKDIR} ${STAGEDIR}${DOCSDIR}
	${INSTALL_DATA} ${WRKSRC}/*.md ${WRKSRC}/docs/*.md ${STAGEDIR}${DOCSDIR}

do-install-EXAMPLES-on:
	@${MKDIR} ${STAGEDIR}${EXAMPLESDIR}
	${INSTALL_DATA} ${WRKSRC}/graph.yaml ${STAGEDIR}${EXAMPLESDIR}

.include <bsd.port.mk>
