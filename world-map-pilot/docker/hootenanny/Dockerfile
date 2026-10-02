FROM hootenanny/run-base-release:latest
ARG PROXY
COPY ca-bundle.crt /etc/pki/ca-trust/source/anchors/agent-proxy.crt
COPY sslibs/ /usr/lib64/
RUN update-ca-trust && ldconfig && \
    echo "proxy=${PROXY}" >> /etc/yum.conf && \
    curl -sS --proxy ${PROXY} -o /etc/yum.repos.d/hoot-release.repo https://hoot-repo.s3.amazonaws.com/el7/release/hoot.repo && \
    sed -i 's/^\[hoot-deps\]/[hoot-deps2]/' /etc/yum.repos.d/hoot-release.repo && \
    curl -sS --proxy ${PROXY} -o /etc/pki/rpm-gpg/hoot.gpg https://hoot-repo.s3.amazonaws.com/el7/hoot.gpg && rpm --import /etc/pki/rpm-gpg/hoot.gpg && \
    yum -y -q --disablerepo='*' --enablerepo='hoot*' --enablerepo='geoint*' makecache >/dev/null 2>&1; (yum --disablerepo='*' --enablerepo='hoot*' --enablerepo='geoint*' install --assumeno hootenanny-core 2>&1 || true) \
      | grep -oE 'Package [^ ]+ [0-9]+:[^ ]+ will be installed' | awk '{print $2}' | sed 's/\.\(x86_64\|noarch\)$//' | sort -u > /tmp/pkgs.txt && \
    cat /tmp/pkgs.txt && mkdir /tmp/rpms && cd /tmp/rpms && \
    yumdownloader --disablerepo='*' --enablerepo='hoot*' --enablerepo='geoint*' $(cat /tmp/pkgs.txt) 2>&1 | tail -3 && ls && \
    rpm -Uvh --nodeps *.rpm 2>&1 | tail -5 && \
    sed -i '/^proxy=/d' /etc/yum.conf && rm -rf /tmp/rpms && yum clean all
