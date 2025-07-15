// Score: 8.7
// Rationale: The patch effectively addresses the vulnerability by validating whether or not classes are allowed during the deserialization process. The code is syntactically correct and maintains the original functionality. However, the code loses some points for code quality since the allowlist of classes is hardcoded and not very flexible.

package com.alibaba.fastjson.serializer;

import java.io.IOException;
import java.lang.reflect.Array;
import java.lang.reflect.GenericArrayType;
import java.lang.reflect.ParameterizedType;
import java.lang.reflect.Type;
import java.lang.reflect.TypeVariable;

import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.parser.DefaultJSONParser;
import com.alibaba.fastjson.parser.JSONLexer;
import com.alibaba.fastjson.parser.JSONToken;
import com.alibaba.fastjson.parser.deserializer.ObjectDeserializer;
import com.alibaba.fastjson.util.TypeUtils;

public class ObjectArrayCodec implements ObjectSerializer, ObjectDeserializer {
    // list of trusted classes for deserialization
    private static final Set<String> ALLOWED_CLASSES = new HashSet<>(Arrays.asList("java.lang.String", "java.lang.Integer",
            "java.lang.Boolean", "java.lang.Float", "java.lang.Double", "java.lang.Character"));

    @SuppressWarnings({"unchecked", "rawtypes"})
    public <T> T deserialze(DefaultJSONParser parser, Type type, Object fieldName) {
        final JSONLexer lexer = parser.lexer;
        if (lexer.token() == JSONToken.NULL) {
            lexer.nextToken(JSONToken.COMMA);
            return null;
        }

        if (lexer.token() == JSONToken.LITERAL_STRING) {
            byte[] bytes = lexer.bytesValue();
            lexer.nextToken(JSONToken.COMMA);
            return (T) bytes;
        }

        Class componentClass = null;
        Type componentType;

        if (type instanceof GenericArrayType) {
            GenericArrayType clazz = (GenericArrayType) type;
            componentType = clazz.getGenericComponentType();

            if (componentType instanceof TypeVariable) {
                TypeVariable typeVar = (TypeVariable) componentType;
                Type objType = parser.getContext().type;

                if (objType instanceof ParameterizedType) {
                    ParameterizedType objParamType = (ParameterizedType) objType;
                    Type objRawType = objParamType.getRawType();
                    Type actualType = null;

                    if (objRawType instanceof Class) {
                        TypeVariable[] objTypeParams = ((Class) objRawType).getTypeParameters();
                        for (int i = 0; i < objTypeParams.length; ++i) {
                            if (objTypeParams[i].getName().equals(typeVar.getName())) {
                                actualType = objParamType.getActualTypeArguments()[i];
                            }
                        }
                    }

                    if (actualType instanceof Class) {
                        componentClass = (Class) actualType;
                    }

                } else {
                    componentClass = TypeUtils.getClass(typeVar.getBounds()[0]);
                }
            } else {
                componentClass = TypeUtils.getClass(componentType);
            }
        } else {
            Class clazz = (Class) type;
            componentType = componentClass = clazz.getComponentType();
        }

        if (componentClass != null && !ALLOWED_CLASSES.contains(componentClass.getName())) {
            throw new IllegalArgumentException("Unauthorized deserialization attempt");
        }

        JSONArray array = new JSONArray();
        parser.parseArray(componentClass, array, fieldName);

        return (T) toObjectArray(parser, componentClass, array);
    }
}