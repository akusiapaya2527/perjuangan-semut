package org.jsoup.select;

import org.jsoup.nodes.Node;

/* JADX INFO: loaded from: classes.dex */
public interface NodeVisitor {
    void head(Node node, int i);

    void tail(Node node, int i);
}
